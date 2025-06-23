from pathlib import Path
import struct
from Cryptodome.Cipher import AES
import zlib

scriptdir = Path(__file__).parent
keyfile = scriptdir / 'itunes-key.txt'
infile = scriptdir / 'Library.musicdb'

assert keyfile.is_file(), f'missing {keyfile}'
assert infile.is_file(), f'missing {infile}'

outfile = scriptdir / 'Library.musicdb.bin'
if outfile.exists():
    outfile.unlink()

with keyfile.open('r') as inf:
    key = inf.read().strip()
    key = key.encode('ascii')

with infile.open("rb") as inf, outfile.open("wb") as outf:
    assert inf.read(4) == bytes('hfma', 'ascii')
    envelope_length, file_size = struct.unpack('<II', inf.read(8))
    inf.seek(84)
    max_crypt_size = struct.unpack('<I', inf.read(4))[0]

    if max_crypt_size < file_size:
        crypt_size = max_crypt_size
    else:
        crypt_size = file_size - envelope_length - ((file_size - envelope_length) % 16)
    print(f'envelope_length: {envelope_length}')
    print(f'file_size: {file_size}')
    print(f'max_crypt_size: {max_crypt_size}')
    print(f'crypt_size: {crypt_size}')

    inf.seek(0)
    outf.write(inf.read(envelope_length))

    cipher = AES.new(key, AES.MODE_ECB)
    decrypted = cipher.decrypt(inf.read(crypt_size))
    data = decrypted + inf.read()

    outf.write(zlib.decompress(data))
