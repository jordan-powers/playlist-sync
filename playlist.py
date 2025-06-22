from pathlib import Path

class Track:
    def __init__(self, track_name: str, track_artist: str, album_name: str, album_artist: str, location: Path, duration: int):
        self.track_name = track_name
        self.track_artist = track_artist
        self.album_name = album_name
        self.album_artist = album_artist
        self.location = location
        self.duration = duration

    def __str__(self) -> str:
        return f"{self.album_artist} - {self.album_name} - {self.track_name} - {str(self.location)}"

class Playlist:
    def __init__(self, name: str, tracks: 'list[Track]'):
        self.name = name
        self.tracks = tracks

    def __str__(self) -> str:
        out = f"Playlist - {self.name}:\n"
        for track in self.tracks:
            out += '  ' + str(track) + '\n'
        return out
