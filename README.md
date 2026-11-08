# Proxmox Autosnap

A simple Python script to manage Proxmox snapshots via `pct` or `qm`.

## Installing

```bash
git clone https://github.com/apprell/proxmox-autosnap.git
ln -s /root/proxmox-autosnap/proxmox-autosnap.py /usr/local/sbin/proxmox-autosnap.py
ln -s /root/proxmox-autosnap/autosnap /etc/cron.d/autosnap
chmod +x /root/proxmox-autosnap/proxmox-autosnap.py
```

## Help

| Arguments             | Required   | Type   | Default   | Description                                                              |
|-----------------------|------------|--------|-----------|--------------------------------------------------------------------------|
| vmid                  | no         | list   | empty     | Space-separated list of CT/VM IDs or `all`.                              |
| snap                  | no         | bool   | false     | Create a snapshot but do not delete anything.                            |
| autosnap              | no         | bool   | false     | Create a snapshot and delete older snapshots beyond the retention limit. |
| keep                  | no         | int    | 30        | The number of snapshots to keep.                                         |
| label                 | no         | str    | daily     | One of `minute`, `hourly`, `daily`, `weekly`, `monthly`.                 |
| clean                 | no         | bool   | false     | Delete all or selected autosnapshots.                                    |
| exclude               | no         | list   | empty     | Space-separated list of CT/VM IDs to exclude from processing.            |
| mute                  | no         | bool   | false     | Output only errors.                                                      |
| running               | no         | bool   | false     | Process only running VMs and containers; skip stopped ones.              |
| includevmstate        | no         | bool   | false     | Include the VM state in snapshots.                                       |
| dryrun                | no         | bool   | false     | Do not create or delete snapshots, just print the commands.              |
| date-iso-format       | no         | bool   | false     | Store snapshots in ISO 8601 format.                                      |
| date-human-format     | no         | bool   | false     | Store snapshots in human-readable format.                                |
| date-truenas-format   | no         | bool   | false     | Store snapshots in TrueNAS format.                                       |
| sudo                  | no         | bool   | false     | Launch commands through sudo.                                            |
| zfs-send-to           | no         | str    | empty     | Send a copy of ZFS volumes to another host via syncoid.                  |
| tags                  | no         | list   | empty     | Space-separated list of tags.                                            |
| exclude-tags          | no         | list   | empty     | Space-separated list of tags to exclude.                                 |
| force                 | no         | bool   | false     | Force removal from the config, even if snapshot deletion fails.          |
| check-free-space      | no         | bool   | false     | Verify sufficient storage space before snapshot creation.                |

> proxmox-autosnap.py --help

## Examples

```bash
# Create a daily snapshot for all VMs
proxmox-autosnap.py --snap --vmid all

# Create snapshots only for running VMs and containers
proxmox-autosnap.py --snap --vmid all --running

# Create a daily snapshot for selected VMs
proxmox-autosnap.py --snap --vmid 100 101 102

# Create a daily snapshot for all VMs except 100, 101, and 102
proxmox-autosnap.py --snap --vmid all --exclude 100 101 102

# Delete all daily autosnapshots for selected VMs
proxmox-autosnap.py --clean --vmid 100 101 102 --keep 0

# Create an hourly snapshot for all VMs
proxmox-autosnap.py --snap --vmid all --label hourly

# Delete all hourly autosnapshots for all VMs
proxmox-autosnap.py --clean --vmid all --label hourly --keep 0

# Create a snapshot with a name in ISO 8601 format
# Example autodaily_2023_03_22T01_26_23
# It is not necessary to specify the --date-iso-format argument to delete snapshots 
proxmox-autosnap.py --snap --vmid 100 --date-iso-format

# Create a snapshot with a name in human-readable format
# Example auto_daily_250303_134506
# It is not necessary to specify the --date-human-format argument to delete snapshots 
proxmox-autosnap.py --snap --vmid 100 --date-human-format

# Create a snapshot with a name in TrueNAS format
# Example autodaily20240212194857
# It is not necessary to specify the --date-truenas-format argument to delete snapshots 
proxmox-autosnap.py --snap --vmid 100 --date-truenas-format

# Create snapshots selected by tags or exclude VMs with specified tags
# Tags are supported only in Proxmox version 7.3 and above
proxmox-autosnap.py --sudo --snap --tags snap --label hourly
proxmox-autosnap.py --sudo --snap --vmid all --label hourly --exclude-tags nosnap
```

## SUDO

To run with the `--sudo` argument, first create a user and grant the required permissions, for example:

`cat /etc/sudoers.d/proxmox-backup`

```bash
Cmnd_Alias VMLIST = /usr/bin/cat /etc/pve/.vmlist
Cmnd_Alias PCT = /usr/sbin/pct snapshot *, /usr/sbin/pct listsnapshot *, /usr/sbin/pct delsnapshot *
Cmnd_Alias QM = /usr/sbin/qm snapshot *, /usr/sbin/qm listsnapshot *, /usr/sbin/qm delsnapshot *
Cmnd_Alias PVESH = /usr/bin/pvesh get /cluster/resources --type vm --output-format json, /usr/bin/pvesh get /nodes/*/storage --content rootdir --enabled 1 --output-format json, /usr/bin/pvesh get /nodes/*/storage/*/content --output-format json
proxmox-backup ALL=NOPASSWD: VMLIST,PCT,QM,PVESH
```

Then run the script with the `--sudo` argument:

```bash
proxmox-autosnap.py --snap --vmid 100 --date-iso-format --sudo
```

## zfs-send-to

To use the `--zfs-send-to` option, install `syncoid` and configure ZFS
permissions on both local and target hosts.
See [documentation on configuring zfs allow for syncoid](https://github.com/jimsalterjrs/sanoid/wiki/Syncoid#running-without-root)
for more information.

Set the option to `[user@]host:zfsdir`. All volumes of the specified VMs
will be copied to this path, including `rootfs` and `mpX` mount points with
the backup option enabled in Proxmox.

## CRON

```bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Task for snapshot every hour from 1 through 23.
5 1-23 * * * root /usr/local/sbin/proxmox-autosnap.py --autosnap --vmid all --label hourly --keep 23 --mute

# Task for snapshot every day-of-month from 2 through 31.
5 0 2-31 * * root /usr/local/sbin/proxmox-autosnap.py --autosnap --vmid all --label daily --keep 30 --mute

# Task for snapshot at 00:05 on day-of-month 1.
5 0 1 * * root /usr/local/sbin/proxmox-autosnap.py --autosnap --vmid all --label monthly --keep 3 --mute
```

```bash
# Task for snapshot every hour from 1 through 23.
5 1-23 * * * root /usr/bin/python3 /etc/pve/bin/autosnap/proxmox-autosnap.py --autosnap --vmid all --label hourly --keep 15 --mute

# Task for snapshot every day-of-month from 2 through 31.
5 0 2-31 * * root /usr/bin/python3 /etc/pve/bin/autosnap/proxmox-autosnap.py --autosnap --vmid all --label daily  --keep  7 --mute
```

> [!WARNING]  
> If the script is stored in `/etc/pve/`, it must be executed with `python` or `python3`, as this directory does not
> support the executable attribute.

## LVM

When using this script with LVM-based storage, it's important to be aware that every time an LVM snapshot is created,
LVM stores a backup of the volume group configuration in the `/etc/lvm/archive` directory. If the snapshot script is
executed frequently (e.g., hourly), this directory can accumulate a large number of files over time, potentially
consuming significant disk space.

To mitigate this, consider setting up a cron job or other cleanup mechanism to periodically remove older files from
`/etc/lvm/archive`. For example:

```bash
# Remove LVM archive files older than 7 days
find /etc/lvm/archive -type f -mtime +7 -delete
```

At the moment, skipping LVM snapshots entirely is not feasible, especially in environments where virtual machines or
containers might use a mix of LVM and ZFS storage backends. Be sure to monitor this directory and adjust your cleanup
policy accordingly.
