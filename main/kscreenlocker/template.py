pkgname = "kscreenlocker"
pkgver = "6.2.1"
pkgrel = 0
build_style = "cmake"
# circular plasma-workspace dep (QML org.kde.plasma.private.sessions) needed by kscreenlocker_greet,
# ksmserver-ksldTest even needs it installed under /usr/lib/libexec
make_check_args = ["-E", "(kscreenlocker-kill|ksmserver-ksld)Test"]
# ksmserver-x11LockerTest only passes under Xvfb
make_check_wrapper = ["dbus-run-session", "xvfb-run"]
hostmakedepends = [
    "cmake",
    "extra-cmake-modules",
    "gettext",
    "ninja",
    "pkgconf",
]
makedepends = [
    "kcmutils-devel",
    "kcrash-devel",
    "kglobalaccel-devel",
    "ki18n-devel",
    "kidletime-devel",
    "kio-devel",
    "knotifications-devel",
    "ksvg-devel",
    "kxmlgui-devel",
    "layer-shell-qt-devel",
    "libkscreen-devel",
    "libplasma-devel",
    "linux-pam-devel",
    "qt6-qtdeclarative-devel",
]
checkdepends = [
    "dbus",
    "xserver-xorg-xvfb",
]
depends = ["kdeclarative"]
pkgdesc = "KDE Library and components for secure lock screen architecture"
maintainer = "Jami Kettunen <jami.kettunen@protonmail.com>"
license = "GPL-2.0-or-later AND (GPL-2.0-only OR GPL-3.0-only)"
url = "https://invent.kde.org/plasma/kscreenlocker"
source = f"$(KDE_SITE)/plasma/{pkgver}/kscreenlocker-{pkgver}.tar.xz"
sha256 = "c3a1730cd75ec8f87eda4c9b5b2f491d59d98b3d06c93f7c3721eea5690b6019"
hardening = ["vis"]


def post_install(self):
    for f in ["kde", "kde-fingerprint", "kde-smartcard"]:
        self.install_file(self.files_path / f"{f}.pam", "usr/lib/pam.d", name=f)


@subpackage("kscreenlocker-devel")
def _(self):
    return self.default_devel()
