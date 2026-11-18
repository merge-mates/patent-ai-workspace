-- DB를 처음 만들 때 한 번만 돈다 (docker-entrypoint-initdb.d). 테이블은 이슈 #55 마이그레이션에서.
CREATE EXTENSION IF NOT EXISTS vector;
