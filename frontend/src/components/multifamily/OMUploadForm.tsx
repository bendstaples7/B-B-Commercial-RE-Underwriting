/**
 * OMUploadForm — drag-and-drop PDF upload form for Commercial OM PDF Intake.
 *
 * Supports:
 *  - Drag-and-drop onto the drop zone
 *  - Click-to-select via hidden file input
 *  - Client-side validation (PDF MIME type, ≤ 50 MB)
 *  - Upload progress indicator
 *  - Navigation to /multifamily/om-intake/:jobId on success
 *
 * Requirements: 1.1, 1.2, 1.3, 6.1
 */
import { useRef, useState, DragEvent, ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  LinearProgress,
  Paper,
  Typography,
} from '@mui/material'
import CloudUploadIcon from '@mui/icons-material/CloudUpload'
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile'
import { omIntakeService } from '@/services/api'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024 // 50 MB

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface OMUploadFormProps {
  onUploadStart?: () => void
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function OMUploadForm({ onUploadStart }: OMUploadFormProps) {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [isDragOver, setIsDragOver] = useState(false)
  const [isUploading, setIsUploading] = useState(false)

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  function validateFile(file: File): string | null {
    if (file.type !== 'application/pdf') {
      return `Invalid file type "${file.type || 'unknown'}". Only PDF files are accepted.`
    }
    if (file.size > MAX_FILE_SIZE_BYTES) {
      return `File is too large (${formatFileSize(file.size)}). Maximum allowed size is 50 MB.`
    }
    return null
  }

  function handleFileSelected(file: File) {
    setUploadError(null)
    const error = validateFile(file)
    if (error) {
      setValidationError(error)
      setSelectedFile(null)
    } else {
      setValidationError(null)
      setSelectedFile(file)
    }
  }

  // ---------------------------------------------------------------------------
  // Drag-and-drop handlers
  // ---------------------------------------------------------------------------

  function handleDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(true)
  }

  function handleDragLeave(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)
  }

  function handleDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOver(false)

    const file = e.dataTransfer.files?.[0]
    if (file) {
      handleFileSelected(file)
    }
  }

  // ---------------------------------------------------------------------------
  // Click-to-select handler
  // ---------------------------------------------------------------------------

  function handleInputChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) {
      handleFileSelected(file)
    }
    // Reset input so the same file can be re-selected after clearing
    e.target.value = ''
  }

  function handleDropZoneClick() {
    fileInputRef.current?.click()
  }

  // ---------------------------------------------------------------------------
  // Submit handler
  // ---------------------------------------------------------------------------

  async function handleSubmit() {
    if (!selectedFile) return

    // Re-validate before submitting (defensive)
    const error = validateFile(selectedFile)
    if (error) {
      setValidationError(error)
      return
    }

    setIsUploading(true)
    setUploadError(null)
    onUploadStart?.()

    try {
      const result = await omIntakeService.uploadOMPDF(selectedFile)
      navigate(`/multifamily/om-intake/${result.intake_job_id}`)
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'An unexpected error occurred during upload.'
      setUploadError(message)
    } finally {
      setIsUploading(false)
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box sx={{ maxWidth: 560, mx: 'auto' }}>
      {/* Drop zone */}
      <Paper
        variant="outlined"
        onClick={handleDropZoneClick}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        aria-label="Drag and drop PDF here, or click to select a file"
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            handleDropZoneClick()
          }
        }}
        sx={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 1.5,
          p: 4,
          cursor: 'pointer',
          border: '2px dashed',
          borderColor: isDragOver ? 'primary.main' : 'divider',
          borderRadius: 2,
          backgroundColor: isDragOver ? 'action.hover' : 'background.paper',
          transition: 'border-color 0.2s, background-color 0.2s',
          '&:hover': {
            borderColor: 'primary.light',
            backgroundColor: 'action.hover',
          },
          '&:focus-visible': {
            outline: '2px solid',
            outlineColor: 'primary.main',
            outlineOffset: 2,
          },
        }}
      >
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf"
          style={{ display: 'none' }}
          onChange={handleInputChange}
          aria-hidden="true"
          tabIndex={-1}
        />

        <CloudUploadIcon
          sx={{ fontSize: 48, color: isDragOver ? 'primary.main' : 'text.secondary' }}
        />

        <Typography variant="body1" color="text.secondary" textAlign="center">
          Drag &amp; drop an OM PDF here, or click to select
        </Typography>

        <Typography variant="caption" color="text.disabled">
          Maximum file size: 50 MB
        </Typography>
      </Paper>

      {/* Selected file info */}
      {selectedFile && !validationError && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            gap: 1,
            mt: 2,
            p: 1.5,
            borderRadius: 1,
            backgroundColor: 'action.selected',
          }}
        >
          <InsertDriveFileIcon color="primary" />
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="body2" fontWeight={500} noWrap>
              {selectedFile.name}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {formatFileSize(selectedFile.size)}
            </Typography>
          </Box>
        </Box>
      )}

      {/* Validation error */}
      {validationError && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {validationError}
        </Alert>
      )}

      {/* Upload error */}
      {uploadError && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {uploadError}
        </Alert>
      )}

      {/* Upload progress */}
      {isUploading && (
        <Box sx={{ mt: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
            <CircularProgress size={16} />
            <Typography variant="body2" color="text.secondary">
              Uploading…
            </Typography>
          </Box>
          <LinearProgress aria-label="Upload progress" />
        </Box>
      )}

      {/* Submit button */}
      <Box sx={{ mt: 3 }}>
        <Button
          variant="contained"
          size="large"
          fullWidth
          disabled={!selectedFile || !!validationError || isUploading}
          onClick={handleSubmit}
          startIcon={isUploading ? <CircularProgress size={18} color="inherit" /> : <CloudUploadIcon />}
          aria-label="Upload OM PDF"
        >
          {isUploading ? 'Uploading…' : 'Upload OM'}
        </Button>
      </Box>
    </Box>
  )
}

export default OMUploadForm
