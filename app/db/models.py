import enum
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    Date,
    Enum,
    JSON,
    ForeignKey,
    Table,
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
    balance = Column(Integer, default=0)
    total_points = Column(Integer, default=0)
    accuracy_rate = Column(Float, default=0.0)
    avg_error = Column(Float, default=0.0)

    forecasts = relationship("Forecast", back_populates="user")


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    full_name = Column(String, nullable=False, unique=True)
    current_rating = Column(Integer)

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

    user = relationship("User", back_populates="forecasts")
    tournament = relationship("Tournament", back_populates="forecasts")
