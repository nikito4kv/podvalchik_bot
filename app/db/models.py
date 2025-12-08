import enum
import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    Enum,
    JSON,
    ForeignKey,
    Table,
    Boolean,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# Таблица для связи многие-ко-многим между Турнирами и Игроками
tournament_participants = Table(
    "tournament_participants",
    Base.metadata,
    Column("tournament_id", ForeignKey("tournaments.id"), primary_key=True),
    Column("player_id", ForeignKey("players.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)  # Telegram ID
    username = Column(String)
    full_name = Column(String, default="") # Real name from Telegram
    balance = Column(Integer, default=0)
    total_points = Column(Integer, default=0)
    total_slots = Column(Integer, default=0) # Общее количество угадываемых мест во всех прогнозах
    
    # New gamification stats
    tournaments_played = Column(Integer, default=0)
    exact_guesses = Column(Integer, default=0)      # 🎯 (5 баллов)
    perfect_tournaments = Column(Integer, default=0) # 💎 (Бонус +15)

    accuracy_rate = Column(Float, default=0.0) # Legacy
    avg_error = Column(Float, default=0.0)     # Legacy

    forecasts = relationship("Forecast", back_populates="user")
    bug_reports = relationship("BugReport", back_populates="user")


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String, nullable=False, unique=True)
    current_rating = Column(Integer)
    is_active = Column(Boolean, default=True)

    # Связь многие-ко-многим с турнирами
    tournaments = relationship(
        "Tournament", secondary=tournament_participants, back_populates="participants"
    )


class TournamentStatus(enum.Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    LIVE = "LIVE"
    FINISHED = "FINISHED"


class Tournament(Base):
    __tablename__ = "tournaments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    status = Column(Enum(TournamentStatus), default=TournamentStatus.DRAFT)
    prediction_count = Column(Integer, default=5)
    results = Column(JSON)  # {"player_id": rank}

    forecasts = relationship("Forecast", back_populates="tournament")
    
    # Связь многие-ко-многим с игроками
    participants = relationship(
        "Player", secondary=tournament_participants, back_populates="tournaments"
    )


class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tournament_id = Column(Integer, ForeignKey("tournaments.id"), nullable=False)
    prediction_data = Column(JSON, nullable=False)  # [player_id_1st, player_id_2nd, ...]
    points_earned = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="forecasts")
    tournament = relationship("Tournament", back_populates="forecasts")


class BugReport(Base):
    __tablename__ = "bug_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    description = Column(String, nullable=False)
    photo_id = Column(String, nullable=True)
    status = Column(String, default="OPEN")  # OPEN, FIXED, REJECTED
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="bug_reports")