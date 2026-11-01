// rag-service의 POST /ask/stream 을 받는 클라이언트
// 브라우저 기본 EventSource는 GET만 되므로 fetch로 받아 SSE를 직접 나눈다

export type Source = { n: number; path: string; pages: string; version: string }

export type SSEEvent = { event: string; data: any }

export type Handlers = {
  onSources: (sources: Source[]) => void
  onToken: (text: string) => void
  onRefused: (answer: string) => void
  onError: (message: string) => void
}

// 받은 글자 덩어리에서 완성된 이벤트만 꺼내고, 덜 온 뒷부분은 rest로 남긴다
// SSE 한 건 = 'event: 이름' + 'data: JSON' + 빈 줄
export function parseSSE(buffer: string): { events: SSEEvent[]; rest: string } {
  const blocks = buffer.replace(/\r\n/g, '\n').split('\n\n')
  const rest = blocks.pop() ?? ''
  const events: SSEEvent[] = []
  for (const block of blocks) {
    let event = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event: ')) event = line.slice(7)
      else if (line.startsWith('data: ')) data += line.slice(6)
    }
    if (data) events.push({ event, data: JSON.parse(data) })
  }
  return { events, rest }
}

// 반환값: 서버가 done 이벤트까지 보냈는지 (false면 중간에 끊긴 것)
export async function askStream(question: string, h: Handlers, signal: AbortSignal): Promise<boolean> {
  const res = await fetch('/api/ask/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
    signal,
  })
  if (!res.ok || !res.body) {
    h.onError(res.status === 422 ? '질문을 확인해 주세요 (1~500자).' : '서버에 연결하지 못했습니다.')
    return true
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let finished = false
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    const { events, rest } = parseSSE(buffer + value)
    buffer = rest
    for (const { event, data } of events) {
      if (event === 'sources') h.onSources(data.sources)
      else if (event === 'token') h.onToken(data.t)
      else if (event === 'refused') h.onRefused(data.answer)
      else if (event === 'error') h.onError(data.message)
      else if (event === 'done') finished = true
    }
  }
  return finished
}
