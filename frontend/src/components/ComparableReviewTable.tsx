import React, { useState } from 'react'
import {
  Box,
  Typography,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Button,
  IconButton,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Grid,
} from '@mui/material'
import DeleteIcon from '@mui/icons-material/Delete'
import AddIcon from '@mui/icons-material/Add'
import {
  ComparableSale,
  PropertyType,
  ConstructionType,
  InteriorCondition,
} from '@/types'

// Feature: gemini-comparable-search, Property 10: Similarity notes truncation threshold
interface SimilarityNotesCellProps {
  similarityNotes: string | null | undefined
}

const SimilarityNotesCell: React.FC<SimilarityNotesCellProps> = ({ similarityNotes }) => {
  const [expanded, setExpanded] = useState(false)

  if (!similarityNotes) {
    return <TableCell />
  }

  if (similarityNotes.length <= 100) {
    return <TableCell>{similarityNotes}</TableCell>
  }

  return (
    <TableCell>
      {expanded ? similarityNotes : similarityNotes.slice(0, 100)}
      <Button size="small" onClick={() => setExpanded((prev) => !prev)} sx={{ ml: 0.5 }}>
        {expanded ? '…less' : '…more'}
      </Button>
    </TableCell>
  )
}

interface ComparableReviewTableProps {
  comparables: ComparableSale[]
  onComparablesChange: (comparables: ComparableSale[]) => void
  onApprove: () => void
  loading?: boolean
}

export const ComparableReviewTable: React.FC<ComparableReviewTableProps> = ({
  comparables,
  onComparablesChange,
  onApprove,
  loading = false,
}) => {
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [newComparable, setNewComparable] = useState<Partial<ComparableSale>>({
    propertyType: PropertyType.SINGLE_FAMILY,
    constructionType: ConstructionType.FRAME,
    interiorCondition: InteriorCondition.AVERAGE,
  })

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  const formatPropertyType = (type: PropertyType) => {
    const labels = {
      [PropertyType.SINGLE_FAMILY]: 'Single Family',
      [PropertyType.MULTI_FAMILY]: 'Multi Family',
      [PropertyType.COMMERCIAL]: 'Commercial',
    }
    return labels[type] || type
  }

  const formatConstructionType = (type: ConstructionType) => {
    const labels = {
      [ConstructionType.FRAME]: 'Frame',
      [ConstructionType.BRICK]: 'Brick',
      [ConstructionType.MASONRY]: 'Masonry',
    }
    return labels[type] || type
  }

  const formatInteriorCondition = (condition: InteriorCondition) => {
    const labels = {
      [InteriorCondition.NEEDS_GUT]: 'Needs Gut',
      [InteriorCondition.POOR]: 'Poor',
      [InteriorCondition.AVERAGE]: 'Average',
      [InteriorCondition.NEW_RENO]: 'New Renovation',
      [InteriorCondition.HIGH_END]: 'High End',
    }
    return labels[condition] || condition
  }

  const formatNumber = (value: number) => {
    return new Intl.NumberFormat('en-US').format(value)
  }

  const handleRemoveComparable = (id: string) => {
    const updatedComparables = comparables.filter((comp) => comp.id !== id)
    onComparablesChange(updatedComparables)
  }

  const handleAddComparable = () => {
    if (
      newComparable.address &&
      newComparable.saleDate &&
      newComparable.salePrice &&
      newComparable.propertyType &&
      newComparable.units !== undefined &&
      newComparable.bedrooms !== undefined &&
      newComparable.bathrooms !== undefined &&
      newComparable.squareFootage !== undefined &&
      newComparable.lotSize !== undefined &&
      newComparable.yearBuilt !== undefined &&
      newComparable.constructionType &&
      newComparable.interiorCondition &&
      newComparable.distanceMiles !== undefined
    ) {
      const comparable: ComparableSale = {
        id: `manual-${Date.now()}`,
        address: newComparable.address,
        saleDate: newComparable.saleDate,
        salePrice: newComparable.salePrice,
        propertyType: newComparable.propertyType,
        units: newComparable.units,
        bedrooms: newComparable.bedrooms,
        bathrooms: newComparable.bathrooms,
        squareFootage: newComparable.squareFootage,
        lotSize: newComparable.lotSize,
        yearBuilt: newComparable.yearBuilt,
        constructionType: newComparable.constructionType,
        interiorCondition: newComparable.interiorCondition,
        distanceMiles: newComparable.distanceMiles,
        coordinates: { lat: 0, lng: 0 }, // Placeholder
      }
      onComparablesChange([...comparables, comparable])
      setAddDialogOpen(false)
      setNewComparable({
        propertyType: PropertyType.SINGLE_FAMILY,
        constructionType: ConstructionType.FRAME,
        interiorCondition: InteriorCondition.AVERAGE,
      })
    }
  }

  const canApprove = comparables.length >= 10

  return (
    <Box>
      <Typography variant="h5" gutterBottom>
        Step 3: Review Comparables
      </Typography>

      <Paper sx={{ p: 3 }}>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">
            {comparables.length} Comparable{comparables.length !== 1 ? 's' : ''}
          </Typography>
          <Button
            variant="outlined"
            startIcon={<AddIcon />}
            onClick={() => setAddDialogOpen(true)}
          >
            Add Comparable
          </Button>
        </Box>

        {!canApprove && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            At least 10 comparables are required to proceed. Currently have {comparables.length}.
          </Alert>
        )}

        <Typography variant="body2" color="text.secondary" gutterBottom>
          Review the comparable sales below. You can remove comparables or add new ones manually.
        </Typography>

        <TableContainer sx={{ mt: 2, maxHeight: 600 }}>
          <Table stickyHeader size="small">
            <TableHead>
              <TableRow>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 200 }}>Address</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }}>Sale Date</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }} align="right">
                  Sale Price
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }}>Property Type</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 80 }} align="right">
                  Units
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 80 }} align="right">
                  Beds
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 80 }} align="right">
                  Baths
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">
                  Sq Ft
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">
                  Lot Size
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">
                  Year Built
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 120 }}>Construction</TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 140 }}>
                  Interior Condition
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="right">
                  Distance
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 200 }}>
                  Similarity Notes
                </TableCell>
                <TableCell sx={{ fontWeight: 'bold', minWidth: 100 }} align="center">
                  Actions
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {comparables.map((comp) => (
                <TableRow key={comp.id} hover>
                  <TableCell>{comp.address}</TableCell>
                  <TableCell>{formatDate(comp.saleDate)}</TableCell>
                  <TableCell align="right">{formatCurrency(comp.salePrice)}</TableCell>
                  <TableCell>{formatPropertyType(comp.propertyType)}</TableCell>
                  <TableCell align="right">{comp.units}</TableCell>
                  <TableCell align="right">{comp.bedrooms}</TableCell>
                  <TableCell align="right">{comp.bathrooms}</TableCell>
                  <TableCell align="right">{formatNumber(comp.squareFootage)}</TableCell>
                  <TableCell align="right">{formatNumber(comp.lotSize)}</TableCell>
                  <TableCell align="right">{comp.yearBuilt}</TableCell>
                  <TableCell>{formatConstructionType(comp.constructionType)}</TableCell>
                  <TableCell>{formatInteriorCondition(comp.interiorCondition)}</TableCell>
                  <TableCell align="right">{comp.distanceMiles.toFixed(2)} mi</TableCell>
                  <SimilarityNotesCell similarityNotes={comp.similarityNotes} />
                  <TableCell align="center">
                    <IconButton
                      size="small"
                      color="error"
                      onClick={() => handleRemoveComparable(comp.id)}
                      title="Remove comparable"
                    >
                      <DeleteIcon fontSize="small" />
                    </IconButton>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>

        <Box sx={{ mt: 3, display: 'flex', justifyContent: 'flex-end' }}>
          <Button
            variant="contained"
            onClick={onApprove}
            disabled={!canApprove || loading}
            size="large"
          >
            Approve & Continue
          </Button>
        </Box>
      </Paper>

      {/* Add Comparable Dialog */}
      <Dialog
        open={addDialogOpen}
        onClose={() => setAddDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>Add Comparable Sale</DialogTitle>
        <DialogContent>
          <Grid container spacing={2} sx={{ mt: 1 }}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Address"
                value={newComparable.address || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, address: e.target.value })
                }
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                label="Sale Date"
                type="date"
                InputLabelProps={{ shrink: true }}
                value={newComparable.saleDate || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, saleDate: e.target.value })
                }
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                label="Sale Price"
                type="number"
                value={newComparable.salePrice || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, salePrice: Number(e.target.value) })
                }
              />
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Property Type</InputLabel>
                <Select
                  value={newComparable.propertyType || PropertyType.SINGLE_FAMILY}
                  onChange={(e) =>
                    setNewComparable({
                      ...newComparable,
                      propertyType: e.target.value as PropertyType,
                    })
                  }
                  label="Property Type"
                >
                  <MenuItem value={PropertyType.SINGLE_FAMILY}>Single Family</MenuItem>
                  <MenuItem value={PropertyType.MULTI_FAMILY}>Multi Family</MenuItem>
                  <MenuItem value={PropertyType.COMMERCIAL}>Commercial</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                label="Units"
                type="number"
                value={newComparable.units || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, units: Number(e.target.value) })
                }
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                fullWidth
                label="Bedrooms"
                type="number"
                value={newComparable.bedrooms || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, bedrooms: Number(e.target.value) })
                }
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                fullWidth
                label="Bathrooms"
                type="number"
                value={newComparable.bathrooms || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, bathrooms: Number(e.target.value) })
                }
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                fullWidth
                label="Square Footage"
                type="number"
                value={newComparable.squareFootage || ''}
                onChange={(e) =>
                  setNewComparable({
                    ...newComparable,
                    squareFootage: Number(e.target.value),
                  })
                }
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                label="Lot Size (sq ft)"
                type="number"
                value={newComparable.lotSize || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, lotSize: Number(e.target.value) })
                }
              />
            </Grid>
            <Grid item xs={6}>
              <TextField
                fullWidth
                label="Year Built"
                type="number"
                value={newComparable.yearBuilt || ''}
                onChange={(e) =>
                  setNewComparable({ ...newComparable, yearBuilt: Number(e.target.value) })
                }
              />
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Construction Type</InputLabel>
                <Select
                  value={newComparable.constructionType || ConstructionType.FRAME}
                  onChange={(e) =>
                    setNewComparable({
                      ...newComparable,
                      constructionType: e.target.value as ConstructionType,
                    })
                  }
                  label="Construction Type"
                >
                  <MenuItem value={ConstructionType.FRAME}>Frame</MenuItem>
                  <MenuItem value={ConstructionType.BRICK}>Brick</MenuItem>
                  <MenuItem value={ConstructionType.MASONRY}>Masonry</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={6}>
              <FormControl fullWidth>
                <InputLabel>Interior Condition</InputLabel>
                <Select
                  value={newComparable.interiorCondition || InteriorCondition.AVERAGE}
                  onChange={(e) =>
                    setNewComparable({
                      ...newComparable,
                      interiorCondition: e.target.value as InteriorCondition,
                    })
                  }
                  label="Interior Condition"
                >
                  <MenuItem value={InteriorCondition.NEEDS_GUT}>Needs Gut</MenuItem>
                  <MenuItem value={InteriorCondition.POOR}>Poor</MenuItem>
                  <MenuItem value={InteriorCondition.AVERAGE}>Average</MenuItem>
                  <MenuItem value={InteriorCondition.NEW_RENO}>New Renovation</MenuItem>
                  <MenuItem value={InteriorCondition.HIGH_END}>High End</MenuItem>
                </Select>
              </FormControl>
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label="Distance (miles)"
                type="number"
                inputProps={{ step: 0.01 }}
                value={newComparable.distanceMiles || ''}
                onChange={(e) =>
                  setNewComparable({
                    ...newComparable,
                    distanceMiles: Number(e.target.value),
                  })
                }
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAddDialogOpen(false)}>Cancel</Button>
          <Button onClick={handleAddComparable} variant="contained">
            Add
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
