# 화면 개발용 이미지. 코드는 compose가 마운트한다 (node_modules는 이미지 것을 씀).
FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev"]
