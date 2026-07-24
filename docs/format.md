# Binary log format v1

Each mutation is one frame:

| Field | Width | Encoding | Meaning |
| --- | ---: | --- | --- |
| magic | 4 bytes | ASCII `MKV1` | File/frame discriminator |
| format version | 1 byte | unsigned | Currently `1` |
| operation | 1 byte | unsigned | `1` put, `2` delete |
| sequence | 8 bytes | big-endian unsigned | Contiguous, starts at `1` |
| key length | 4 bytes | big-endian unsigned | `1..1024` bytes |
| value length | 4 bytes | big-endian unsigned | `0..1,048,576` bytes |
| key | variable | strict UTF-8 NFC | No NUL |
| value | variable | opaque bytes | Empty is valid for put |
| checksum | 4 bytes | big-endian CRC32 | Covers header, key, and value |

A delete frame must have a zero value length. Unknown versions, operations, or
fields cannot be skipped because v1 has no extension mechanism.

## Recovery classification

- Fewer bytes than a complete final header: torn tail, truncate to prior frame.
- Header is valid but declared body/checksum is incomplete: torn tail, truncate.
- Complete frame with any invalid field or checksum: corruption, preserve bytes
  and fail startup.

This distinction avoids silently discarding a complete but damaged mutation.

## Resource policy

The default database limit is 64 MiB and the hard configurable ceiling is
1 GiB. Declared lengths are validated before reading the body. The entire file
size is bounded before scanning. These limits constrain startup work and prevent
malformed lengths from triggering unbounded allocation.

CRC32 is an accidental-corruption check, not a signature or message
authentication code.

## Canonical compacted form

A compacted v1 log contains exactly one put frame for each live key. Keys are
ordered by Python's deterministic Unicode code-point ordering after NFC
normalization. Sequence numbers restart at one and remain contiguous. There are
no delete frames or superseded values. Therefore identical logical state
produces identical compacted bytes on the same format version.

## Backup artifact format v1

A backup artifact begins with one fixed-width 56-byte header followed by a
canonical compacted log payload:

| Field | Width | Encoding | Meaning |
| --- | ---: | --- | --- |
| magic | 4 bytes | ASCII `MKB1` | Backup discriminator |
| backup version | 1 byte | unsigned | Currently `1` |
| log format | 1 byte | unsigned | Currently MiniKV log v1 |
| reserved | 2 bytes | unsigned | Must be zero |
| entry count | 8 bytes | big-endian unsigned | Live entries in payload |
| payload length | 8 bytes | big-endian unsigned | Exact following byte count |
| payload digest | 32 bytes | SHA-256 | Digest of payload only |
| payload | variable | MiniKV log v1 | Complete canonical compacted form |

Unknown versions, non-zero reserved bits, truncation, trailing bytes, length or
digest mismatch, non-canonical payloads, count mismatch, and any ordinary log
violation are rejected before restore changes its destination. Artifact size is
bounded by the configured database limit plus the fixed header.

SHA-256 provides corruption evidence and deterministic lineage. It does not
authenticate who created the backup; a malicious writer can replace both
payload and digest.

## Lock sidecar

The `.DATABASE_NAME.lock` sibling is coordination metadata, not part of the
binary database or backup format. It contains no keys, values, identifiers, or
authoritative state. Its inode is the POSIX advisory-lock rendezvous point, so
it persists after close and must not be copied as database content or deleted
while any process may use the database.
