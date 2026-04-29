## GitHub 배포 가이드

### GitHub 리포지토리 생성

1. GitHub에서 새 리포지토리 생성
2. 로컬 설정 완료

### 리모트 등록 및 푸시

```bash
# 리모트 추가
git remote add origin https://github.com/TLSRUF/xagent-pay-api.git

# 메인 브랜치 푸시
git push -u origin master
```

### 다음 단계

- [ ] README.md에 본인 GitHub 리포지토리 URL로 업데이트
- [ ] .env.example 파일대신 실제 .env 파일로 설정
- [ ] 프로덕션 배포 시 JWT_SECRET 등 보안 설정 강화

