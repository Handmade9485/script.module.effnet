import json
import numpy as np
import essentia
from essentia.standard import MonoLoader, TensorflowPredictEffnetDiscogs
import sqlite3
import os
import fire

essentia.EssentiaLogger().warningActive = False

DB_PATH = "./resources/effnet.db"

AUDIO_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a"}

def is_audio_file(filename):
    return os.path.splitext(filename.lower())[1] in AUDIO_EXTS

def cosine_distance(a, b):
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    return float(1.0 - np.dot(a, b))



class MusicDB:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        conn = self._connect()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS songs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kodi_song_id INTEGER,
            path TEXT NOT NULL UNIQUE,
            embedding BLOB NOT NULL
        )
        """)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS song_distances (
            song_a_id INTEGER NOT NULL,
            song_b_id INTEGER NOT NULL,
            distance REAL NOT NULL,

            PRIMARY KEY (song_a_id, song_b_id),

            FOREIGN KEY (song_a_id) REFERENCES songs(id),
            FOREIGN KEY (song_b_id) REFERENCES songs(id)
        )
        """)

        conn.commit()
        conn.close()

    def embed(self, root_dir, force=False):
        """
        Generate embeddings for all audio files.
        """

        conn = self._connect()
        cur = conn.cursor()
        model = TensorflowPredictEffnetDiscogs(graphFilename="models/discogs-effnet-bs64-1.pb")

        def analyze_file(path):
            try:
                if not force:
                    cur.execute("SELECT 1 FROM songs WHERE path = ? LIMIT 1", (path,))
                    if cur.fetchone():
                        print(f"SKIP: {path}")
                        return

                audio = MonoLoader(filename=path, sampleRate=16000, resampleQuality=4)()
                embeddings = model(audio)
                # pool over time → single vector
                song_vector = np.mean(embeddings, axis=0).astype(np.float32)
                blob = song_vector.tobytes()
                cur.execute("""
                    INSERT INTO songs (path, embedding)
                    VALUES (?, ?)
                    ON CONFLICT(path)
                    DO UPDATE SET embedding = excluded.embedding
                """, (path, blob))
                print(f"SUCCESS: {path}")
            except Exception as e:
                print(f"FAIL: {path} -> {e}")

        for root, _, files in os.walk(root_dir):
            for file in files:
                if not is_audio_file(file):
                    continue
                full_path = os.path.join(root, file)
                analyze_file(full_path)
                conn.commit()
        conn.close()

    def distances(self):
        """
        Compute pairwise cosine distances.
        """

        conn = self._connect()
        cur = conn.cursor()

        cur.execute("SELECT id, embedding FROM songs ORDER BY id")
        rows = cur.fetchall()

        songs = []

        for song_id, blob in rows:
            vec = np.frombuffer(blob, dtype=np.float32)
            songs.append((song_id, vec))

        song_count = len(songs)
        print(f"Loaded {song_count} songs")

        for i in range(song_count):
            id_a, vec_a = songs[i]
            if i % 100 == 0:
                print(f"{i+1}/{song_count}")

            for j in range(i + 1, song_count):
                id_b, vec_b = songs[j]
                dist = cosine_distance(vec_a, vec_b)
                if dist < 0.5:
                    cur.execute("""
                        INSERT OR REPLACE INTO song_distances
                        (song_a_id, song_b_id, distance)
                        VALUES (?, ?, ?)
                    """, (id_a, id_b, dist))
            conn.commit()
        conn.close()


if __name__ == "__main__":
    fire.Fire(MusicDB)
