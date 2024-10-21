
Debian
====================
This directory contains files used to package yerbasd/yerbas-qt
for Debian-based Linux systems. If you compile yerbasd/yerbas-qt yourself, there are some useful files here.

## yerbas: URI support ##


yerbas-qt.desktop  (Gnome / Open Desktop)
To install:

	sudo desktop-file-install yerbas-qt.desktop
	sudo update-desktop-database

If you build yourself, you will either need to modify the paths in
the .desktop file or copy or symlink your yerbas-qt binary to `/usr/bin`
and the `../../share/pixmaps/yerbas128.png` to `/usr/share/pixmaps`

yerbas-qt.protocol (KDE)

