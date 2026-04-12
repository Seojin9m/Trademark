import { useState, useRef, useEffect, memo } from "react"
import { MessageSquare, X, Send, Trash2, Square } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  type TextMessagePartComponent,
} from "@assistant-ui/react"
import { useAuiState } from "@assistant-ui/store"
import { cn } from "@/lib/utils"
import { ChatRuntimeProvider } from "./ChatRuntimeProvider"

// ─── Markdown renderer ──────────────────────────────────────────────────────
// Memoized so re-renders with the same `text` (e.g. from parent state changes)
// skip the markdown parse entirely. During streaming, only the actively-growing
// message has its text change, so older bubbles never re-parse.

const MarkdownContent = memo(function MarkdownContent({ text }: { text: string }) {
  return (
    <div
      className={cn(
        "prose-chat",
        "[&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
        "[&_p]:my-1.5 [&_p]:leading-relaxed",
        "[&_strong]:font-semibold [&_strong]:text-foreground",
        "[&_em]:italic",
        "[&_ul]:my-1.5 [&_ul]:pl-4 [&_ul]:list-disc [&_ul]:space-y-0.5",
        "[&_ol]:my-1.5 [&_ol]:pl-4 [&_ol]:list-decimal [&_ol]:space-y-0.5",
        "[&_li]:leading-relaxed",
        "[&_h1]:text-base [&_h1]:font-semibold [&_h1]:mt-3 [&_h1]:mb-1.5",
        "[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mt-3 [&_h2]:mb-1.5",
        "[&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-2 [&_h3]:mb-1",
        "[&_code]:rounded [&_code]:bg-background/60 [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-[0.85em] [&_code]:font-mono",
        "[&_pre]:rounded-lg [&_pre]:bg-background/60 [&_pre]:p-2 [&_pre]:my-1.5 [&_pre]:overflow-x-auto",
        "[&_pre_code]:bg-transparent [&_pre_code]:p-0",
        "[&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2",
        "[&_blockquote]:border-l-2 [&_blockquote]:border-border [&_blockquote]:pl-2 [&_blockquote]:italic [&_blockquote]:opacity-80",
        "[&_table]:my-1.5 [&_table]:border-collapse [&_table]:text-xs",
        "[&_th]:border [&_th]:border-border/50 [&_th]:px-1.5 [&_th]:py-0.5 [&_th]:font-semibold [&_th]:text-left",
        "[&_td]:border [&_td]:border-border/50 [&_td]:px-1.5 [&_td]:py-0.5",
        "[&_hr]:my-2 [&_hr]:border-border/40",
      )}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  )
})

// Custom Text part component plugged into MessagePrimitive.Parts.
// assistant-ui calls this only with the text that belongs to *this* part,
// and re-renders only when that part's text changes — exactly the perf
// optimization we need.
//
// Markdown parsing is O(n) per parse and runs on *every* re-render while the
// text is growing — that's the real source of streaming lag. So while the
// part is still running we render plain text (whitespace preserved) and only
// flip to the full markdown renderer once the stream finishes. The final
// markdown render runs exactly once per message.
const AssistantText: TextMessagePartComponent = ({ text }) => {
  // Message-level running state — documented and reliably flips to false
  // when the async generator in the adapter returns. Part-level status does
  // not always flip back for LocalRuntime.
  const isRunning = useAuiState(
    (s: { message: { status: { type: string } } }) =>
      s.message.status.type === "running",
  )
  if (isRunning) {
    return (
      <div className="whitespace-pre-wrap break-words leading-relaxed">
        {text}
      </div>
    )
  }
  return <MarkdownContent text={text} />
}

// ─── Message components ────────────────────────────────────────────────────

function UserMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-end">
      <div className="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed bg-primary text-primary-foreground whitespace-pre-wrap break-words">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  )
}

function AssistantMessage() {
  return (
    <MessagePrimitive.Root className="flex justify-start">
      <div className="max-w-[85%] rounded-xl px-3.5 py-2.5 text-sm leading-relaxed bg-muted/80 text-foreground border border-border/30 break-words">
        <MessagePrimitive.Parts components={{ Text: AssistantText }} />
      </div>
    </MessagePrimitive.Root>
  )
}

// ─── Composer ──────────────────────────────────────────────────────────────

function ChatComposer() {
  return (
    <ComposerPrimitive.Root className="border-t border-border/40 px-3 py-2.5">
      <div className="flex items-end gap-2">
        <ComposerPrimitive.Input
          rows={1}
          placeholder="Ask about your portfolio..."
          submitMode="enter"
          className={cn(
            "flex-1 resize-none rounded-xl border border-border/50 bg-muted/30",
            "px-3 py-2 text-sm placeholder:text-muted-foreground/60",
            "focus:outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20",
            "max-h-24 overflow-y-auto",
          )}
        />
        <ThreadPrimitive.If running={false}>
          <ComposerPrimitive.Send asChild>
            <button
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title="Send"
            >
              <Send className="h-3.5 w-3.5" />
            </button>
          </ComposerPrimitive.Send>
        </ThreadPrimitive.If>
        <ThreadPrimitive.If running>
          <ComposerPrimitive.Cancel asChild>
            <button
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-destructive text-white hover:bg-destructive/90 transition-colors"
              title="Stop"
            >
              <Square className="h-3.5 w-3.5" />
            </button>
          </ComposerPrimitive.Cancel>
        </ThreadPrimitive.If>
      </div>
    </ComposerPrimitive.Root>
  )
}

// ─── Empty state ───────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center text-muted-foreground py-12">
      <MessageSquare className="h-8 w-8 mb-3 opacity-40" />
      <p className="text-sm font-medium">Ask me anything</p>
      <p className="text-xs mt-1 max-w-[250px]">
        Portfolio, trades, factor scores, risk metrics, news research, and more.
      </p>
    </div>
  )
}

// ─── Inner panel (lives inside the runtime provider) ──────────────────────

function ChatPanel({
  onClose,
  onClear,
}: {
  onClose: () => void
  onClear: () => void
}) {
  const inputContainerRef = useRef<HTMLDivElement>(null)

  // Focus the composer textarea when the panel mounts
  useEffect(() => {
    const ta = inputContainerRef.current?.querySelector("textarea")
    ta?.focus()
  }, [])

  return (
    <div
      className={cn(
        "fixed bottom-5 right-5 z-40",
        "flex flex-col w-[400px] h-[560px]",
        "rounded-2xl border border-border/60 bg-background",
        "shadow-2xl shadow-black/20",
        "animate-fade-in",
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border/40">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">Talk to My Data</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            onClick={onClear}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title="Clear chat"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            title="Close"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* Thread */}
      <ThreadPrimitive.Root className="flex flex-col flex-1 min-h-0">
        <ThreadPrimitive.Viewport
          autoScroll
          className="flex-1 overflow-y-auto px-4 py-3 space-y-3"
        >
          <ThreadPrimitive.Empty>
            <EmptyState />
          </ThreadPrimitive.Empty>
          <ThreadPrimitive.Messages
            components={{
              UserMessage,
              AssistantMessage,
            }}
          />
        </ThreadPrimitive.Viewport>
        <div ref={inputContainerRef}>
          <ChatComposer />
        </div>
      </ThreadPrimitive.Root>
    </div>
  )
}

// ─── Top-level widget ──────────────────────────────────────────────────────

export function ChatWidget() {
  const [open, setOpen] = useState(false)
  // Bumping this key force-remounts the runtime provider, which clears all
  // assistant-ui state. Simpler than digging into the imperative reset API
  // and works regardless of which version of the runtime is installed.
  const [resetKey, setResetKey] = useState(0)
  // Lifted out of the provider so the clear-button handler can read it
  // before remounting (the new provider gets a fresh ref).
  const sessionIdRef = useRef<string | null>(null)

  const handleClear = () => {
    const sid = sessionIdRef.current
    if (sid) {
      fetch(`/api/chat/${sid}`, { method: "DELETE" }).catch(() => {})
    }
    sessionIdRef.current = null
    setResetKey((k) => k + 1)
  }

  return (
    <>
      {/* Floating toggle button — always visible when panel is closed */}
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className={cn(
            "fixed bottom-5 right-5 z-40",
            "flex h-12 w-12 items-center justify-center rounded-full",
            "bg-primary text-primary-foreground shadow-lg shadow-primary/25",
            "hover:bg-primary/90 hover:scale-105 active:scale-95",
            "transition-all duration-200",
          )}
          title="Talk to My Data"
        >
          <MessageSquare className="h-5 w-5" />
        </button>
      )}

      {/* Runtime provider stays mounted while the panel is open so the user's
          conversation persists if they close and reopen the toggle. */}
      {open && (
        <ChatRuntimeProvider key={resetKey} sessionIdRef={sessionIdRef}>
          <ChatPanel onClose={() => setOpen(false)} onClear={handleClear} />
        </ChatRuntimeProvider>
      )}
    </>
  )
}
