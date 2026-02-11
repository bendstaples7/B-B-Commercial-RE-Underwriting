import React from 'react'
import {
  Box,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
  Chip,
} from '@mui/material'
import { RankedComparable } from '@/types'

interface WeightedScoringTableProps {
  rankedComparables: RankedComparable[]
}

export const WeightedScoringTable: React.FC<WeightedScoringTableProps> = ({
  rankedComparables,
}) => {
  const formatScore = (score: number): string => {
    return score.toFixed(1)
  }

  const isTopFive = (rank: number): boolean => {
    return rank <= 5
  }

  return (
    <Box sx={{ px: { xs: 1, sm: 2 } }} component="section" aria-labelledby="weighted-scoring-heading">
      <Typography variant="h5" gutterBottom id="weighted-scoring-heading">
        Step 4: Weighted Scoring & Ranking
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: { xs: 2, sm: 3 } }}>
        Comparables ranked by similarity to subject property using weighted criteria
      </Typography>

      <TableContainer 
        component={Paper} 
        sx={{ 
          maxHeight: { xs: 400, sm: 500, md: 600 },
          overflowX: 'auto',
        }}
        role="region"
        aria-labelledby="weighted-scoring-heading"
      >
        <Table stickyHeader size="small" aria-label="Weighted scoring and ranking table">
          <TableHead>
            <TableRow>
              <TableCell sx={{ fontWeight: 'bold', minWidth: 60 }} scope="col">Rank</TableCell>
              <TableCell sx={{ fontWeight: 'bold', minWidth: { xs: 150, sm: 200 } }} scope="col">Address</TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 80, sm: 100 } }} scope="col">
                Recency
                <br />
                <Typography variant="caption" color="text.secondary">
                  (16%)
                </Typography>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 80, sm: 100 } }} scope="col">
                Proximity
                <br />
                <Typography variant="caption" color="text.secondary">
                  (15%)
                </Typography>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 80, sm: 100 } }} scope="col">
                Units
                <br />
                <Typography variant="caption" color="text.secondary">
                  (15%)
                </Typography>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 80, sm: 100 } }} scope="col">
                Beds/Baths
                <br />
                <Typography variant="caption" color="text.secondary">
                  (15%)
                </Typography>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 80, sm: 100 } }} scope="col">
                Sq Ft
                <br />
                <Typography variant="caption" color="text.secondary">
                  (15%)
                </Typography>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 100, sm: 120 } }} scope="col">
                Construction
                <br />
                <Typography variant="caption" color="text.secondary">
                  (12%)
                </Typography>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 80, sm: 100 } }} scope="col">
                Interior
                <br />
                <Typography variant="caption" color="text.secondary">
                  (12%)
                </Typography>
              </TableCell>
              <TableCell align="center" sx={{ fontWeight: 'bold', minWidth: { xs: 100, sm: 120 } }} scope="col">
                Total Score
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rankedComparables.map((ranked) => {
              const topFive = isTopFive(ranked.rank)
              return (
                <TableRow
                  key={ranked.comparable.id}
                  sx={{
                    backgroundColor: topFive ? 'action.hover' : 'inherit',
                    '&:hover': {
                      backgroundColor: topFive ? 'action.selected' : 'action.hover',
                    },
                  }}
                  aria-label={topFive ? `Top ranked comparable ${ranked.rank}` : undefined}
                >
                  <TableCell>
                    {topFive ? (
                      <Chip
                        label={ranked.rank}
                        color="primary"
                        size="small"
                        sx={{ fontWeight: 'bold' }}
                        aria-label={`Rank ${ranked.rank}, top 5 comparable`}
                      />
                    ) : (
                      <Typography variant="body2">{ranked.rank}</Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <Typography 
                      variant="body2" 
                      sx={{ 
                        fontWeight: topFive ? 'bold' : 'normal',
                        fontSize: { xs: '0.75rem', sm: '0.875rem' },
                      }}
                    >
                      {ranked.comparable.address}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                      {formatScore(ranked.scoreBreakdown.recencyScore)}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                      {formatScore(ranked.scoreBreakdown.proximityScore)}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                      {formatScore(ranked.scoreBreakdown.unitsScore)}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                      {formatScore(ranked.scoreBreakdown.bedsBathsScore)}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                      {formatScore(ranked.scoreBreakdown.sqftScore)}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                      {formatScore(ranked.scoreBreakdown.constructionScore)}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography variant="body2" sx={{ fontSize: { xs: '0.75rem', sm: '0.875rem' } }}>
                      {formatScore(ranked.scoreBreakdown.interiorScore)}
                    </Typography>
                  </TableCell>
                  <TableCell align="center">
                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: 'bold',
                        color: topFive ? 'primary.main' : 'text.primary',
                        fontSize: { xs: '0.75rem', sm: '0.875rem' },
                      }}
                    >
                      {formatScore(ranked.totalScore)}
                    </Typography>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {rankedComparables.length > 0 && (
        <Box sx={{ mt: 2 }} role="note" aria-label="Information about top comparables">
          <Typography variant="caption" color="text.secondary">
            Top 5 comparables (highlighted) will be used for valuation models
          </Typography>
        </Box>
      )}
    </Box>
  )
}
