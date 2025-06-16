import sqlite3
from typing import Optional, List, Dict, Any
import datetime


class MovieDatabase:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_tables()

    def _ensure_tables(self):
        """Создает таблицы, если они еще не существуют."""
        cursor = self.conn.cursor()
        cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tmdb_id INTEGER UNIQUE,
            title TEXT,
            original_title TEXT,
            overview TEXT,
            release_date TEXT,
            vote_average REAL,
            poster_path TEXT,
            genres TEXT,
            directors TEXT,
            actors TEXT,
            runtime INTEGER
        );

        CREATE TABLE IF NOT EXISTS preferences (
            user_id INTEGER,
            preference_type TEXT,
            preference_value TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS ratings (
            user_id INTEGER,
            movie_id INTEGER,
            rating INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        );

        CREATE TABLE IF NOT EXISTS history (
            user_id INTEGER,
            movie_id INTEGER,
            action_type TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (movie_id) REFERENCES movies(id)
        );
        """)
        self.conn.commit()

    def get_user(self, user_id: int) -> Optional[sqlite3.Row]:
        cur = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return cur.fetchone()

    def add_user(self, user_id: int, username: str):
        self.conn.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user_id, username))
        self.conn.commit()

    def get_user_preferences(self, user_id: int) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT preference_type, preference_value FROM preferences WHERE user_id = ?", (user_id,))
        return [dict(row) for row in cur.fetchall()]

    def clear_user_preferences(self, user_id: int):
        self.conn.execute("DELETE FROM preferences WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def clear_user_history(self, user_id: int):
        self.conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
        self.conn.commit()

    def get_user_history(self, user_id: int) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT * FROM history WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
        return [dict(row) for row in cur.fetchall()]

    def get_user_history_count(self, user_id: int) -> int:
        cur = self.conn.execute("SELECT COUNT(*) as count FROM history WHERE user_id = ?", (user_id,))
        return cur.fetchone()["count"]

    def get_movie(self, movie_id: int) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM movies WHERE id = ?", (movie_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_movie_by_tmdb_id(self, tmdb_id: int) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM movies WHERE tmdb_id = ?", (tmdb_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def add_movie(self, movie: Dict[str, Any]) -> Optional[int]:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO movies 
            (tmdb_id, title, original_title, overview, release_date, vote_average, poster_path, genres, directors, actors, runtime)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            movie.get('tmdb_id'),
            movie.get('title'),
            movie.get('original_title'),
            movie.get('overview'),
            movie.get('release_date'),
            movie.get('vote_average'),
            movie.get('poster_path'),
            ', '.join(movie.get('genres', [])),
            ', '.join(movie.get('directors', [])),
            ', '.join(movie.get('actors', [])),
            movie.get('runtime')
        ))
        self.conn.commit()
        return cursor.lastrowid

    def add_user_history(self, user_id: int, movie_id: int, action_type: str):
        self.conn.execute("""
            INSERT INTO history (user_id, movie_id, action_type) 
            VALUES (?, ?, ?)
        """, (user_id, movie_id, action_type))
        self.conn.commit()

    def get_user_ratings(self, user_id: int) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT movie_id, rating FROM ratings WHERE user_id = ? ORDER BY timestamp DESC", (user_id,))
        return [dict(row) for row in cur.fetchall()]

    def add_rating(self, user_id: int, movie_id: int, rating: int):
        self.conn.execute("""
            INSERT INTO ratings (user_id, movie_id, rating) 
            VALUES (?, ?, ?) 
            ON CONFLICT(user_id, movie_id) DO UPDATE SET rating = excluded.rating
        """, (user_id, movie_id, rating))
        self.conn.commit()
