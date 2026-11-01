import type { Metadata, Viewport } from 'next'

import './globals.css'

export const metadata: Metadata = {
  title: '감염관리 지침 도우미 · HappyNurse',
  description: '의료관련감염 표준예방지침 기반 질의응답',
}

export const viewport: Viewport = { width: 'device-width', initialScale: 1 }

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="font-sans antialiased">{children}</body>
    </html>
  )
}
