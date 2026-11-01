import assert from 'node:assert/strict'
import { test } from 'node:test'

import { moveCites } from './cite.ts'

test('번호는 줄 끝 마침표 뒤로, 문장 중간 번호와 범위 밖 번호는 뺀다', () => {
  assert.equal(moveCites('닦아요 [1].', 3), '닦아요. [1]')
  assert.equal(moveCites('먼저 [2] 흡수시켜요 [1, 2]', 3), '먼저 흡수시켜요. [1, 2]')
  assert.equal(moveCites('• 소독해요 [3.2.2.4] [38, 58].', 3), '• 소독해요.')
  assert.equal(moveCites('첫 줄이에요 [1].\n\n• 둘째 [3].', 3), '첫 줄이에요. [1]\n\n• 둘째. [3]')
})
