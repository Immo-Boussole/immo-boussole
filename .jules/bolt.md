## 2025-05-18 - [Fast Bitwise Distance for Perceptual Image Hashes]
**Learning:** Computing Hamming distance between hex string perceptual hashes (dHash/aHash) using Python's `int(h1, 16) ^ int(h2, 16)` combined with `int.bit_count()` is ~16x faster than zip-iterating hex string characters and counting bits per character.
**Action:** Always prefer native bitwise XOR and `bit_count()` for integer or hex bit-string distance computations in Python 3.10+.
