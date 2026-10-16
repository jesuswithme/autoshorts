# 오토 쇼핑 쇼츠 작업 폴더

이 폴더에서 쇼핑 쇼츠를 만들 때는 `skill/SKILL.md` 의 절차를 그대로 따른다 (`__SSM_HOME__` = 이 저장소 폴더의 절대경로).
- 엔진: Windows `ssm.cmd <명령>` / macOS·Linux `./ssm <명령>` (new / add / collect / analyze / clean / init-script / build / frames / voices / doctor)
- 대본 결 템플릿: `skill/references/tones.md`
- 운영 팁, 저작권 주의: `skill/references/ops_tips.md`
- 설정 기본값: `config.json` / 영상별 덮어쓰기: `projects/<이름>/config.override.json`
- analyze/clean/build 는 오래 걸릴 수 있으니 쉘 타임아웃을 넉넉히 (10분) 준다.
