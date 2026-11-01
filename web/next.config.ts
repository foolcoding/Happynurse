import type { NextConfig } from 'next'

// 브라우저는 같은 주소의 /api/* 만 부르고, Next가 rag-service(FastAPI)로 넘겨준다
// → FastAPI에 CORS 설정이 필요 없음. 앱(안드로이드)은 rag-service를 직접 부르면 됨
const ragApi = process.env.RAG_API_URL || 'http://127.0.0.1:8000'

const nextConfig: NextConfig = {
  compress: false,    // gzip 압축이 SSE를 모았다가 한 번에 보내서 스트리밍이 끊김 → 끔
  experimental: { proxyTimeout: 120_000 },    // 프록시 기본 30초 제한 → 모델 첫 로딩 등 느린 응답이 잘리지 않게
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${ragApi}/:path*` }]
  },
}

export default nextConfig
