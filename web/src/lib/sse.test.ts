// 실행: npm test (Node 내장 테스트 러너)
import assert from 'node:assert/strict'
import { test } from 'node:test'

import { parseSSE } from './sse.ts'

test('완성된 이벤트만 꺼내고 덜 온 부분은 남긴다', () => {
  const { events, rest } = parseSSE('event: token\ndata: {"t":"손"}\n\nevent: token\ndata: {"t":')
  assert.deepEqual(events, [{ event: 'token', data: { t: '손' } }])
  assert.equal(rest, 'event: token\ndata: {"t":')
})

test('남은 부분과 이어 붙이면 이어서 꺼낸다', () => {
  const first = parseSSE('event: token\ndata: {"t":')
  const { events } = parseSSE(first.rest + '"위생"}\n\nevent: done\ndata: {}\n\n')
  assert.deepEqual(events.map((e) => e.event), ['token', 'done'])
  assert.equal(events[0].data.t, '위생')
})

test('답 안의 줄바꿈과 \\r\\n 줄끝을 깨뜨리지 않는다', () => {
  const { events } = parseSSE('event: token\r\ndata: {"t":"첫 줄\\n둘째 줄"}\r\n\r\n')
  assert.equal(events[0].data.t, '첫 줄\n둘째 줄')
})
