from pathlib import Path
import json
import html

from playlist import Playlist, PlaylistReader
from itunes import iTunesReader
from applemusic import AppleMusicReader, AppleMusicLibraryDecryptor

settings_path = Path(__file__).parent / 'settings.json'
with settings_path.open("r") as inf:
    settings = json.load(inf)

keyfile = Path(__file__).parent / 'itunes-key.txt'
assert keyfile.exists(), f"Missing keyfile at {keyfile}"

applemusic_lib_path = Path(settings['Apple Music Library Path'])
itunes_lib_path = Path(settings['iTunes Library Path'])
groove_playlist_path = Path(settings['Groove Playlist Directory'])
playlist_names = set(plist.lower() for plist in settings['Playlists'])

if not applemusic_lib_path.is_file():
    print("Could not find Apple Music library!")
    exit(1)

if not itunes_lib_path.is_file():
    print("Could not find iTunes library!")
    exit(1)

if not groove_playlist_path.is_dir():
    print("Invalid Groove playlist directory!")
    exit(1)

parsed_playlists: 'list[Playlist]' = []

with keyfile.open('r') as inf:
    key = inf.read().strip()
    key = key.encode('ascii')

decryptor = AppleMusicLibraryDecryptor(key, applemusic_lib_path)
applemusic = AppleMusicReader.load_file(decryptor.decrypt())
itunes = iTunesReader(itunes_lib_path)

readers: 'list[PlaylistReader]' = [applemusic, itunes]
for reader in readers:
    for playlist in reader.read_playlists():
        lname = playlist.name.lower()
        if lname in playlist_names:
            playlist_names.remove(lname)
            parsed_playlists.append(playlist)

zpl_template = """
<?zpl version="2.0"?>
<smil>
  <head>
    <meta name="generator" content="Entertainment Platform -- 10.22031.1009.0" />
    <meta name="itemCount" content="{item_count}" />
    <meta name="totalDuration" content="{total_duration_ms}" />
    <title>{title}</title>
  </head>
  <body>
    <seq>
{items}
    </seq>
  </body>
</smil>
""".lstrip()

zpl_item_template = '      <media src="{src}" albumTitle="{album_title}" albumArtist="{album_artist}" trackTitle="{track_title}" trackArtist="{track_artist}" duration="{duration}" />'

for plist in parsed_playlists:
    zpl_items = []
    total_duration = 0
    for track in plist.tracks:
        total_duration += track.duration
        zpl_items.append(zpl_item_template.format(
            src=html.escape(str(track.location)),
            album_title=html.escape(track.album_name),
            album_artist=html.escape(track.album_artist),
            track_title=html.escape(track.track_name),
            track_artist=html.escape(track.track_artist),
            duration=track.duration
        ))

    zpl_playlist = zpl_template.format(
        item_count=len(plist.tracks),
        total_duration_ms=total_duration,
        title=html.escape(plist.name),
        items='\n'.join(zpl_items)
    )

    zpl_out_path = groove_playlist_path / (plist.name + ".zpl")
    with zpl_out_path.open("w") as outf:
        outf.write(zpl_playlist)
