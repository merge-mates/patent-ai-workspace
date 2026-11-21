"""API 테스트용 사건 저장소 단위(#16): 메모리 저장소 + 커밋 흉내. DB 없음."""

from patent_ai.core.f1_oa_reader.case_repository import InMemoryCaseRepository


class FakeRepoUnit:
    """get_case_repository_unit 대신 끼운다. fail_commit이면 DB 저장 실패를 흉내 낸다."""

    def __init__(self, repo=None, fail_commit=False):
        self.repo = repo if repo is not None else InMemoryCaseRepository()
        self.fail_commit = fail_commit
        self.commits = 0

    def commit(self):
        if self.fail_commit:
            raise RuntimeError("DB 저장 실패 흉내")
        self.commits += 1

    def rollback(self):
        pass
