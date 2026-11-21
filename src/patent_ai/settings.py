"""환경마다 다른 값 (환경 변수·.env에서 읽음). 실험 값(모델 등)은 config/·experiments/에 둔다."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 기본값은 각자 맥의 로컬 compose DB (compose.yaml 기본 계정).
    # 컨테이너 안에서는 compose가 db 서비스 주소로 바꿔 넘긴다.
    database_url: str = "postgresql+psycopg://patent:patent@localhost:5432/patent_ai"
    # 올린 OA PDF 원본을 두는 곳 (git 밖). 컨테이너에서는 compose가 ./work를 /app/work로 마운트한다
    upload_dir: str = "work/uploads"


@lru_cache
def get_settings() -> Settings:
    return Settings()
