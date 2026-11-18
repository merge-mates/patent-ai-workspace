"""DB 모델(SQLAlchemy ORM)의 공통 Base. 테이블은 이슈 #55에서 이 Base를 상속해 만든다."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
