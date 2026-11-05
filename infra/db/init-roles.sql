-- 로컬 docker compose 전용. 앱 계정은 bjk_app 역할에 속하고 RLS를 우회하지 못한다.
-- 운영 DB에서는 같은 구조로 계정을 만들고 비밀번호는 별도로 관리한다.
CREATE ROLE bjk_app NOLOGIN;
CREATE ROLE bjk_app_login LOGIN PASSWORD 'bjk_app_login' IN ROLE bjk_app;
