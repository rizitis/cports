import subprocess
import os
import re
import glob
import shutil
import shlex
import getpass
import pathlib
from tempfile import mkstemp

from cbuild.core import logger, paths
from cbuild import cpu

_chroot_checked = False
_chroot_ready = False

def chroot_check():
    global _chroot_checked, _chroot_ready

    if _chroot_checked:
        return _chroot_ready

    _chroot_checked = True

    if (paths.masterdir() / ".cbuild_chroot_init").is_file():
        _chroot_ready = True
        cpun = (paths.masterdir() / ".cbuild_chroot_init").read_text().strip()
        cpu.init(cpun, cpun)
    else:
        cpun = os.uname().machine
        cpu.init(cpun, cpun)

    return _chroot_ready

def _subst_in(pat, rep, src, dest = None):
    inf = open(src, "r")
    if dest:
        outf = open(dest, "w")
    else:
        fd, nm = mkstemp()
        outf = open(nm, "w")

    for line in inf:
        out = re.sub(pat, rep, line)
        outf.write(out)

    inf.close()
    outf.close()

    if not dest:
        shutil.move(nm, src)

def _remove_ro(f, path, _):
    os.chmod(path, stat.S_IWRITE)
    f(path)

def _init():
    xdir = paths.masterdir() / "etc" / "apk"
    os.makedirs(xdir, exist_ok = True)

    shf = open(paths.masterdir() / "bin" / "cbuild-shell", "w")
    shf.write(f"""#!/bin/sh

PATH=/void-packages:/usr/bin

exec env -i -- SHELL=/bin/sh PATH="$PATH" \
    CBUILD_ARCH={cpu.host()} \
    IN_CHROOT=1 LC_COLLATE=C LANG=en_US.UTF-8 TERM=linux HOME="/tmp" \
    PS1="[\\u@{str(paths.masterdir())} \\W]$ " /bin/sh
""")
    shf.close()

    (paths.masterdir() / "bin" / "cbuild-shell").chmod(0o755)

    shutil.copy("/etc/resolv.conf", paths.masterdir() / "etc")

def _prepare(arch = None):
    sfpath = paths.masterdir() / ".cbuild_chroot_init"
    if sfpath.is_file():
        return
    if not (paths.masterdir() / "usr" / "bin" / "sh").is_file():
        logger.get().out_red("cbuild: bootstrap not installed, can't continue")
        raise Exception()

    if pathlib.Path("/usr/share/zoneinfo/UTC").is_file():
        zpath = paths.masterdir() / "usr" / "share" / "zoneinfo"
        os.makedirs(zpath, exist_ok = True)
        shutil.copy("/usr/share/zoneinfo/UTC", zpath)
        (paths.masterdir() / "etc" / "localtime").symlink_to(
            "../usr/share/zoneinfo/UTC"
        )
    else:
        logger.get().out(
            "cbuild: no local timezone configuration file created"
        )

    for f in ["dev", "sys", "tmp", "proc", "host", "boot", "void-packages"]:
        os.makedirs(paths.masterdir() / f, exist_ok = True)

    shutil.copy(
        paths.templates() / "base-files" / "files" / "passwd",
        paths.masterdir() / "etc"
    )
    shutil.copy(
        paths.templates() / "base-files" / "files" / "group",
        paths.masterdir() / "etc"
    )
    shutil.copy(
        paths.templates() / "base-files" / "files" / "hosts",
        paths.masterdir() / "etc"
    )

    with open(paths.masterdir() / "etc" / "passwd", "a") as pf:
        username = getpass.getuser()
        gid = os.getgid()
        uid = os.getuid()
        pf.write(f"{username}:x:{uid}:{gid}:{username} user:/tmp:/bin/cbuild-shell\n")

    with open(paths.masterdir() / "etc" / "group", "a") as pf:
        pf.write(f"{username}:x:{gid}:\n")

    with open(sfpath, "w") as sf:
        sf.write(arch + "\n")

def repo_sync():
    confdir = paths.masterdir() / "etc/apk"

    os.makedirs(confdir, exist_ok = True)

    shutil.copy2(paths.distdir() / "etc/apk/repositories", confdir)

    # copy over apk public keys
    keydir = paths.masterdir() / "etc/apk/keys"

    shutil.rmtree(keydir, ignore_errors = True)
    os.makedirs(keydir, exist_ok = True)

    for f in (paths.distdir() / "etc/keys").glob("*.pub"):
        shutil.copy2(f, keydir)

    # do not refresh if chroot is not initialized
    if not (paths.masterdir() / ".cbuild_chroot_init").is_file():
        return

    if enter("apk", ["update"]).returncode != 0:
        logger.get().out_red(f"cbuild: failed to update pkg database")
        raise Exception()

def reconfigure():
    if not chroot_check():
        return

    statefile = paths.masterdir() / ".cbuild_chroot_configured"

    if statefile.is_file():
        return

    logger.get().out("cbuild: reconfiguring base...")

    if enter("update-ca-certificates", ["--fresh"]).returncode != 0:
        logger.get().out_red(f"cbuild: failed to reconfigure base")
        raise Exception()

    statefile.touch()

def initdb():
    # we init the database ourselves
    mdir = paths.masterdir()
    os.makedirs(mdir / "tmp", exist_ok = True)
    os.makedirs(mdir / "dev", exist_ok = True)
    os.makedirs(mdir / "etc/apk", exist_ok = True)
    os.makedirs(mdir / "usr/lib/apk/db", exist_ok = True)
    os.makedirs(mdir / "var/cache/apk", exist_ok = True)
    os.makedirs(mdir / "var/cache/misc", exist_ok = True)

    # largely because of custom usrmerge
    if not (mdir / "lib").is_symlink():
        (mdir / "lib").symlink_to("usr/lib")

    (mdir / "usr/lib/apk/db/installed").touch()
    (mdir / "etc/apk/world").touch()

def install(arch = None, bootstrap = False):
    if chroot_check():
        return

    logger.get().out("cbuild: installing base-chroot...")

    initdb()

    oldh = cpu.host()
    oldt = cpu.target()
    try:
        cpu.init(arch, oldt)
        repo_sync()
    finally:
        cpu.init(oldh, oldt)

    if not arch or bootstrap:
        arch = cpu.host()

    irun = subprocess.run([
        "apk", "add", "--root", str(paths.masterdir()), "--no-scripts",
        "--repositories-file", str(paths.distdir() / "etc/apk/repositories_host"),
        "--arch", arch, "base-chroot"
    ])
    if irun.returncode != 0:
        logger.get().out_red("cbuild: failed to install base-chroot")
        raise Exception()

    logger.get().out("cbuild: installed base-chroot successfully!")

    _prepare(arch)
    _chroot_checked = False
    _chroot_ready = False
    chroot_check()
    _init()

def update(do_clean = True):
    if not chroot_check():
        return

    reconfigure()

    logger.get().out("cbuild: updating software in %s masterdir..." \
        % str(paths.masterdir()))

def enter(cmd, args = [], capture_out = False, check = False,
          env = {}, stdout = None, stderr = None, wrkdir = None,
          bootstrapping = False):
    envs = {
        "PATH": "/usr/bin:" + os.environ["PATH"],
        "SHELL": "/bin/sh",
        "HOME": "/tmp",
        "IN_CHROOT": "1",
        "LC_COLLATE": "C",
        "LANG": "en_US.UTF-8",
        **env
    }
    if "NO_PROXY" in os.environ:
        envs["NO_PROXY"] = os.environ["NO_PROXY"]
    if "FTP_PROXY" in os.environ:
        envs["FTP_PROXY"] = os.environ["FTP_PROXY"]
    if "HTTP_PROXY" in os.environ:
        envs["HTTP_PROXY"] = os.environ["HTTP_PROXY"]
    if "HTTPS_PROXY" in os.environ:
        envs["HTTPS_PROXY"] = os.environ["HTTPS_PROXY"]
    if "SOCKS_PROXY" in os.environ:
        envs["SOCKS_PROXY"] = os.environ["SOCKS_PROXY"]
    if "FTP_RETRIES" in os.environ:
        envs["FTP_RETRIES"] = os.environ["FTP_RETRIES"]
    if "HTTP_PROXY_AUTH" in os.environ:
        envs["HTTP_PROXY_AUTH"] = os.environ["HTTP_PROXY_AUTH"]

    # if running from template, ensure wrappers are early in executable path
    if "CBUILD_STATEDIR" in envs:
        envs["PATH"] = envs["CBUILD_STATEDIR"] + "/wrappers:" + envs["PATH"]

    if bootstrapping:
        return subprocess.run(
            [cmd] + args, env = envs,
            capture_output = capture_out, check = check,
            stdout = stdout, stderr = stderr,
            cwd = os.path.abspath(wrkdir) if wrkdir else None
        )

    bcmd = [
        "bwrap",
        "--dev-bind", str(paths.masterdir()), "/",
        "--dev-bind", str(paths.hostdir()), "/host",
        "--dev-bind", str(paths.distdir()), "/void-packages",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
    ]

    if wrkdir:
        bcmd.append("--chdir")
        bcmd.append(str(wrkdir))

    bcmd.append(cmd)
    bcmd += args

    return subprocess.run(
        bcmd, env = envs, capture_output = capture_out, check = check,
        stdout = stdout, stderr = stderr
    )
