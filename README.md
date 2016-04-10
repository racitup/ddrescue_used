#ddrescue_used
Python ddrescue-based hard disk recovery tool, but only recovers used filesystem space.

##Description:
Uses several techniques to try to recover only used parts of hard disks instead of the whole disk.
- First tries to clone supported filesystems using the relevant clone tool, see *Filesystem support* below
- If clone is successful, later unnecessary operations are skipped
- Starts a disk trace to record accessed hard disk blocks
- Reads and checks the partition table giving the user the option to repair using testdisk
- Scans each filesystem found to detect metadata blocks using fsck or similar
- Transfers the partition table and metadata to the image using ddrescue
- Finds used data blocks either directly like du, or indirectly by finding free space
- Transfers the data to the image using ddrescue
- Optionally diffs the source and destination filesystems to validate itself
- ddrescue stages are resumable

##Usage:
1. Download using: `git clone https://github.com/racitup/ddrescue_used.git`
2. `cd ddrescue_used`
3. `chmod u+x ddrescue_used.py`
4. `./ddrescue_used -h` to print a list of dependency problems (if any) and usage help
5. The tool must be run as root (sudo) since it uses Linux commands that only root can run, such as mount

##Recommendations

###Destination disk:
The destination filesystem should support both sparse files and compression, like btrfs.
Ensure you have sufficient destination disk space. You should only need the same space as is used on the source disk, but more is better!

###Disable automounting:
In Ubuntu (and probably many other distributions) filesystems will be automounted when they are attached and detected. This will interfere with tool behaviour and *must* be disabled:
1. Install dconf-editor (`sudo apt-get install dconf-editor`)
2. Navigate to `org.gnome.desktop.media-handling`
3. Disable `automount` and `automount-open`

This may also be configured in other places, e.g.:
**Settings -> Removable Drives and Media -> Storage -> Removable Storage**:
- Mount removable drives when hot-plugged
- Mount removable media when inserted
- Browse removable media when inserted
These should all be unticked (disabled)

##Status:
This tool is in Alpha testing.

The source disk is only ever used read-only, so the source data is safe.
Please do not rely on the image created to be a reliable copy. Make use of the -d switch to diff the source with the image after the copy is created if you want to validate the image content.
Use on failing hard disks at your own risk. If your data is valuable please use another recovery tool until this tool is properly validated. Testing with errored disks is ongoing.

##Filesystem support:
The first thing the tool does is check for dependencies. It is only required to install the dependencies for the filesystems that you wish to recover.

Filesystem | Clone | Default Used Method | Notes
-----------|-------|---------------------|-------
vfat       |  No   |        Free         |
ext2/3/4   |  Yes  | 2/3: Used, 4: Free  |
hfsplus    |  No   |        Free         |
ntfs       |  Yes  |        Used         |
xfs        |  Yes  |        Free         |
btrfs*     |  Yes  |        Free         | Clone only supports metadata, data is transferred separately

*btrfs support is restricted to single device filesystems. Multiple device filesystems are not supported and will cause the tool to fail. This is because the kernel uses the UUID to scan for sibling filesystems and gets confused when presented with the image which has an identical UUID. btrfstune -u has been tried to rectify this but at current moment causes filesystem corruption. There is no plan to fix btrfs support.

Filesystem support can be expanded if supported by Linux.

##Reporting bugs:
Please use the following command to create a log for reporting bugs. Note that this log may contain data from your disk that you may deem to be sensitive. Please sanitise as appropriate:
`./ddrescue_used -kvvd <device> <disk.img> <destdir> 2> err.log`

It is not recommended to pipe stdout to a file since the tool is at places interactive. Please paste stdout into a file separately if necessary. The -k option leaves log files in the destination which can be useful for debugging.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.

