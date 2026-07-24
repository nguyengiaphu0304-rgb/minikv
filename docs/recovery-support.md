# Recovery support matrix

| Environment | Evidence | Status |
| --- | --- | --- |
| GitHub Ubuntu, CPython 3.11–3.13, local runner filesystem | CI unit, fault-injection, abrupt-process, compaction, backup/restore, reopen, demo, and isolated-wheel checks | Verified |
| Other local POSIX systems with working `flock`, `fsync`, and atomic same-directory replacement | Contract documented; expected to work | Not independently verified |
| Windows | Lifetime lock intentionally rejects non-POSIX systems | Unsupported |
| NFS, SMB, object mounts, distributed or unusual userspace filesystems | Lock and durability semantics may differ | Unsupported |
| Physical power interruption and storage-controller cache loss | No hardware fault rig | Unverified |

Recovery tests deliberately distinguish failures before and after atomic
replacement. Before replacement, tests require preservation of authoritative
bytes. After replacement, a directory `fsync` failure is reported as durability
uncertainty rather than a false rollback claim.

This matrix describes tested evidence, not a certification of a filesystem,
kernel, virtual machine, or storage device.
