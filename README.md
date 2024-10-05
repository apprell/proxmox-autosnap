# Proxmox Autosnap

A simple script written on python to control zfs proxmox snapshots via pct or qm.

## Installing

```bash
git clone https://github.com/apprell/proxmox-autosnap.git
ln -s /root/proxmox-autosnap/proxmox-autosnap.py /usr/local/sbin/proxmox-autosnap.py
ln -s /root/proxmox-autosnap/autosnap /etc/cron.d/autosnap
chmod +x /root/proxmox-autosnap/proxmox-autosnap.py
```

## Help

| Arguments           | Required | Type | Default | Description                                                   |
|---------------------|----------|------|---------|---------------------------------------------------------------|
| vmid                | no       | list | empty   | Space separated list of CT/VM IDs or `all`.                   |
| snap                | no       | bool | false   | Create a snapshot but do not delete anything.                 |
| autosnap            | no       | bool | false   | Create a snapshot and delete the old one.                     |
| keep                | no       | int  | 30      | The number of snapshots which should will keep.               |
| label               | no       | str  | daily   | One of `minute`, `hourly`, `daily`, `weekly`, `monthly`.      |
| clean               | no       | bool | false   | Delete all or selected autosnapshots.                         |
| exclude             | no       | list | empty   | Space separated list of CT/VM IDs to exclude from processing. |
| mute                | no       | bool | false   | Output only errors.                                           |
| running             | no       | bool | false   | Run only on running vm, skip on stopped.                      |
| includevmstate      | no       | bool | false   | Include the VM state in snapshots.                            |
| dryrun              | no       | bool | false   | Do not create or delete snapshots, just print the commands.   |
| date-iso-format     | no       | bool | false   | Store snapshots in ISO 8601 format.                           |
| date-truenas-format | no       | bool | false   | Store snapshots in TrueNAS format.                            |
| sudo                | no       | bool | false   | Launch commands through sudo.                                 |
| zfs-send-to         | no       | str  | empty   | Send a copy of zfs subvolumes to another host via syncoid     |
| tags                | no       | list | empty   | Space separated list of tags                                  |
| exclude-tags        | no       | list | empty   | Space separated list of tags to exclude                       |

> proxmox-autosnap.py --help

## Examples

```bash
# Create a daily snapshot for all VM
proxmox-autosnap.py --snap --vmid all

# Create snapshot only on running vm
proxmox-autosnap.py --snap --vmid all --running

# Create a daily snapshot for selected VM
proxmox-autosnap.py --snap --vmid 100 101 102

# Create a daily snapshot for all VM with the exception of 100 101 102
proxmox-autosnap.py --snap --vmid all --exclude 100 101 102

# Delete all daily autosnapshots for selected VM
proxmox-autosnap.py --clean --vmid 100 101 102 --keep 0

# Create a hourly snapshot for all VM
proxmox-autosnap.py --snap --vmid all --label hourly

# Delete all hourly autosnapshots for all VM
proxmox-autosnap.py --clean --vmid all --label hourly --keep 0

# Create a snapshot name in ISO 8601 format
# Example autodaily_2023_03_22T01_26_23
# It is not necessary to specify the --date-iso-format argument to delete snapshots 
proxmox-autosnap.py --snap --vmid 100 --date-iso-format

# Create a snapshot name in TrueNAS format
# Example autodaily20240212194857
# It is not necessary to specify the --date-truenas-format argument to delete snapshots 
proxmox-autosnap.py --snap --vmid 100 --date-truenas-format

# Create a snapshot filtered by tags and exclude tags
# Tags are supported only in Proxmox version 7.3 and above
proxmox-autosnap.py --sudo --snap --tags snap --label hourly
proxmox-autosnap.py --sudo --snap --vmid all --label hourly --exclude-tags nosnap
```

## SUDO

In order to run with sudo argument, you must first create a user and specify minimum accesses for him, for example:

`cat /etc/sudoers.d/proxmox-backup`

```bash
Cmnd_Alias VMLIST = /usr/bin/cat /etc/pve/.vmlist
Cmnd_Alias PCT = /usr/sbin/pct snapshot *, /usr/sbin/pct listsnapshot *, /usr/sbin/pct delsnapshot *
Cmnd_Alias QM = /usr/sbin/qm snapshot *, /usr/sbin/qm listsnapshot *, /usr/sbin/qm delsnapshot *
Cmnd_Alias PVESH = /usr/bin/pvesh get /cluster/resources --type vm --output-format json
proxmox-backup ALL=NOPASSWD: VMLIST,PCT,QM,PVESH
```

After that you can run the script with the argument

```bash
proxmox-autosnap.py --snap --vmid 100 --date-iso-format --sudo
```

## zfs-send-to

To use option `zfs-send-to`, you need to install `syncoid`, and enable zfs
permissions on both local and target hosts. See [documentation on configuring zfs allow for syncoid](https://github.com/jimsalterjrs/sanoid/wiki/Syncoid#running-without-root)
for more information.

Option should be set to `[user@]host:zfsdir`. All subvolumes of specified VMs
will be copied to this path, including `rootfs` and `mpX` mount points with
backup option enabled on Proxmox.

## Cron

```bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin

# Task for snapshot every hour from 1 through 23.
5 1-23 * * * root /usr/local/sbin/proxmox-autosnap.py --autosnap --vmid all --label hourly --keep 23 --mute

# Task for snapshot every day-of-month from 2 through 31.
5 0 2-31 * * root /usr/local/sbin/proxmox-autosnap.py --autosnap --vmid all --label daily --keep 30 --mute

# Task for snapshot at 00:05 on day-of-month 1.
5 0 1 * * root /usr/local/sbin/proxmox-autosnap.py --autosnap --vmid all --label monthly --keep 3 --mute
```
