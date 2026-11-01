// 문장 중간의 번호를 빼서 줄 끝 마침표 뒤에 한 번만: '닦아요 [1].' → '닦아요. [1]'
// [1], [1, 3] 뿐 아니라 [3.2.2.4] 같은 조항 번호도 잡아서, 출처 번호가 아니면 지움
export function moveCites(text: string, count: number) {
  return text
    .split('\n')
    .map((line) => {
      const ns = new Set<number>()
      const rest = line
        .replace(/\s*\[(\d+(?:\s*[.,~-]\s*\d+)*)\]/g, (m, inner: string, at: number) => {
          const xs = inner.split(/\s*,\s*/)
          if (xs.every((n) => /^\d+$/.test(n) && +n >= 1 && +n <= count)) xs.forEach((n) => ns.add(+n))
          return /[^\s.,?!]/.test(line[at + m.length] ?? '') ? ' ' : '' // 단어 사이였으면 띄어쓰기는 남김
        })
        .trimEnd()
      if (!ns.size) return rest
      return `${/[.?]$/.test(rest) ? rest : `${rest}.`} [${[...ns].sort((a, b) => a - b).join(', ')}]`
    })
    .join('\n')
}
