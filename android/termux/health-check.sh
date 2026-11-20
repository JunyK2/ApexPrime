#!/data/data/com.termux/files/usr/bin/bash
set +e
printf '%s\n' '--- Android ---'
getprop ro.build.version.release
getprop ro.product.model
printf '%s\n' '--- Bateria ---'
termux-battery-status
printf '%s\n' '--- Wi-Fi ---'
termux-wifi-connectioninfo
printf '%s\n' '--- Daemon ---'
pgrep -af 'apexprime.daemon'
