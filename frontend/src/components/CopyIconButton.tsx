import { useState } from 'react'
import { IconButton, Tooltip } from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'

export interface CopyIconButtonProps {
  /** Text written to the clipboard. */
  value: string
  ariaLabel?: string
  testId?: string
  fontSize?: number
}

/** Compact copy-to-clipboard icon button shared by contact / PIN rows. */
export function CopyIconButton({
  value,
  ariaLabel = 'Copy',
  testId,
  fontSize = 14,
}: CopyIconButtonProps) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    void navigator.clipboard.writeText(value).then(
      () => {
        setCopied(true)
        window.setTimeout(() => setCopied(false), 1500)
      },
      () => {
        /* Clipboard denied / insecure context — leave idle label. */
      },
    )
  }
  return (
    <Tooltip title={copied ? 'Copied!' : 'Copy'}>
      <IconButton
        size="small"
        onClick={(e) => {
          e.stopPropagation()
          handleCopy()
        }}
        aria-label={ariaLabel}
        data-testid={testId}
        sx={{ p: 0.25, flexShrink: 0 }}
      >
        <ContentCopyIcon sx={{ fontSize }} />
      </IconButton>
    </Tooltip>
  )
}
