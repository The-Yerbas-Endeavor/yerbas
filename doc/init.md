Sample init scripts and service configuration for yerbasd
==========================================================

Sample scripts and configuration files for systemd, Upstart and OpenRC
can be found in the contrib/init folder.

    contrib/init/yerbasd.service:    systemd service unit configuration
    contrib/init/yerbasd.openrc:     OpenRC compatible SysV style init script
    contrib/init/yerbasd.openrcconf: OpenRC conf.d file
    contrib/init/yerbasd.conf:       Upstart service configuration file
    contrib/init/yerbasd.init:       CentOS compatible SysV style init script

Service User
---------------------------------

All three Linux startup configurations assume the existence of a "yerbascore" user
and group.  They must be created before attempting to use these scripts.
The OS X configuration assumes yerbasd will be set up for the current user.

Configuration
---------------------------------

At a bare minimum, yerbasd requires that the rpcpassword setting be set
when running as a daemon.  If the configuration file does not exist or this
setting is not set, yerbasd will shutdown promptly after startup.

This password does not have to be remembered or typed as it is mostly used
as a fixed token that yerbasd and client programs read from the configuration
file, however it is recommended that a strong and secure password be used
as this password is security critical to securing the wallet should the
wallet be enabled.

If yerbasd is run with the "-server" flag (set by default), and no rpcpassword is set,
it will use a special cookie file for authentication. The cookie is generated with random
content when the daemon starts, and deleted when it exits. Read access to this file
controls who can access it through RPC.

By default the cookie is stored in the data directory, but it's location can be overridden
with the option '-rpccookiefile'.

This allows for running yerbasd without having to do any manual configuration.

`conf`, `pid`, and `wallet` accept relative paths which are interpreted as
relative to the data directory. `wallet` *only* supports relative paths.

For an example configuration file that describes the configuration settings,
see `contrib/debian/examples/yerbas.conf`.

Paths
---------------------------------

### Linux

All three configurations assume several paths that might need to be adjusted.

Binary:              `/usr/bin/yerbasd`  
Configuration file:  `/etc/yerbascore/yerbas.conf`  
Data directory:      `/var/lib/yerbasd`  
PID file:            `/var/run/yerbasd/yerbasd.pid` (OpenRC and Upstart) or `/var/lib/yerbasd/yerbasd.pid` (systemd)  
Lock file:           `/var/lock/subsys/yerbasd` (CentOS)  

The configuration file, PID directory (if applicable) and data directory
should all be owned by the yerbascore user and group.  It is advised for security
reasons to make the configuration file and data directory only readable by the
yerbascore user and group.  Access to yerbas-cli and other yerbasd rpc clients
can then be controlled by group membership.

### Mac OS X

Binary:              `/usr/local/bin/yerbasd`  
Configuration file:  `~/Library/Application Support/YerbasCore/yerbas.conf`  
Data directory:      `~/Library/Application Support/YerbasCore`
Lock file:           `~/Library/Application Support/YerbasCore/.lock`

Installing Service Configuration
-----------------------------------

### systemd

Installing this .service file consists of just copying it to
/usr/lib/systemd/system directory, followed by the command
`systemctl daemon-reload` in order to update running systemd configuration.

To test, run `systemctl start yerbasd` and to enable for system startup run
`systemctl enable yerbasd`

### OpenRC

Rename yerbasd.openrc to yerbasd and drop it in /etc/init.d.  Double
check ownership and permissions and make it executable.  Test it with
`/etc/init.d/yerbasd start` and configure it to run on startup with
`rc-update add yerbasd`

### Upstart (for Debian/Ubuntu based distributions)

Drop yerbasd.conf in /etc/init.  Test by running `service yerbasd start`
it will automatically start on reboot.

NOTE: This script is incompatible with CentOS 5 and Amazon Linux 2014 as they
use old versions of Upstart and do not supply the start-stop-daemon utility.

### CentOS

Copy yerbasd.init to /etc/init.d/yerbasd. Test by running `service yerbasd start`.

Using this script, you can adjust the path and flags to the yerbasd program by
setting the YERBASD and FLAGS environment variables in the file
/etc/sysconfig/yerbasd. You can also use the DAEMONOPTS environment variable here.

### Mac OS X

Copy org.yerbas.yerbasd.plist into ~/Library/LaunchAgents. Load the launch agent by
running `launchctl load ~/Library/LaunchAgents/org.yerbas.yerbasd.plist`.

This Launch Agent will cause yerbasd to start whenever the user logs in.

NOTE: This approach is intended for those wanting to run yerbasd as the current user.
You will need to modify org.yerbas.yerbasd.plist if you intend to use it as a
Launch Daemon with a dedicated yerbascore user.

Auto-respawn
-----------------------------------

Auto respawning is currently only configured for Upstart and systemd.
Reasonable defaults have been chosen but YMMV.
