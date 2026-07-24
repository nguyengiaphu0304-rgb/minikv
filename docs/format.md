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
