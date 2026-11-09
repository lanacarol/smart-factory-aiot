// Renderizador de Markdown minimo para a saida do LLM.
// A resposta do modelo e texto NAO confiavel:
// - todo HTML e escapado antes de qualquer formatacao;
// - nao gera <img> nem links (nada e carregado de fora).
// Suporta: titulos, negrito, italico, codigo, listas e paragrafos.

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function inline(text: string): string {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
}

export function renderSafeMarkdown(source: string): string {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const html: string[] = []
  let list: 'ul' | 'ol' | null = null
  let paragraph: string[] = []
  let inCode = false
  let code: string[] = []

  const flushParagraph = () => {
    if (paragraph.length) {
      html.push(`<p>${paragraph.map(inline).join('<br>')}</p>`)
      paragraph = []
    }
  }

  const closeList = () => {
    if (list) {
      html.push(`</${list}>`)
      list = null
    }
  }

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (inCode) {
        html.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`)
        code = []
        inCode = false
      } else {
        flushParagraph()
        closeList()
        inCode = true
      }
      continue
    }

    if (inCode) {
      code.push(line)
      continue
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    const bullet = line.match(/^\s*[-*]\s+(.*)$/)
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/)

    if (heading) {
      flushParagraph()
      closeList()
      html.push(`<h4>${inline(heading[2] ?? '')}</h4>`)
    } else if (bullet || numbered) {
      flushParagraph()
      const kind = bullet ? 'ul' : 'ol'
      if (list !== kind) {
        closeList()
        html.push(`<${kind}>`)
        list = kind
      }
      html.push(`<li>${inline((bullet ?? numbered)?.[1] ?? '')}</li>`)
    } else if (line.trim() === '') {
      flushParagraph()
      closeList()
    } else {
      closeList()
      paragraph.push(line)
    }
  }

  if (inCode) {
    html.push(`<pre><code>${escapeHtml(code.join('\n'))}</code></pre>`)
  }

  flushParagraph()
  closeList()

  return html.join('')
}
