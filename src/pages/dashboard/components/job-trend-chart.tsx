import React, { useMemo } from 'react';
import {
  Container,
  Header,
  Box,
  SpaceBetween,
  Spinner,
  Button,
  BarChart,
} from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';
import { DailyJobCount } from '../hooks';

interface JobTrendChartProps {
  data: DailyJobCount[] | undefined;
  loading: boolean;
}

// Status color mapping - same as job-stats-card
const STATUS_COLORS: Record<string, string> = {
  SUCCESS: '#037f0c',    // Green
  ERROR: '#d13212',      // Red
  RUNNING: '#0972d3',    // Blue
  PENDING: '#879596',    // Gray
  SUBMITTED: '#5f6b7a',  // Dark gray
  CREATING: '#ec7211',   // Orange
  TERMINATED: '#414d5c', // Dark
  TERMINATING: '#8d6605', // Yellow-brown
  STOPPED: '#414d5c',    // Dark
};

// Get the last 7 days including today
function getLast7Days(): string[] {
  const dates: string[] = [];
  const today = new Date();
  for (let i = 6; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(today.getDate() - i);
    dates.push(date.toISOString().split('T')[0]);
  }
  return dates;
}

// Format date for display (MM-DD)
function formatDateForDisplay(dateStr: string): string {
  const date = new Date(dateStr);
  const month = (date.getMonth() + 1).toString().padStart(2, '0');
  const day = date.getDate().toString().padStart(2, '0');
  return `${month}-${day}`;
}

export function JobTrendChart({ data, loading }: JobTrendChartProps) {
  const { t } = useTranslation();

  // Process data into series format
  const { series, categories, hasData, maxY } = useMemo(() => {
    const last7Days = getLast7Days();
    const categories = last7Days.map(formatDateForDisplay);

    if (!data || data.length === 0) {
      return { series: [], categories, hasData: false, maxY: 10 };
    }

    // Group data by status
    const statusMap: Record<string, Record<string, number>> = {};
    data.forEach((item) => {
      if (!statusMap[item.status]) {
        statusMap[item.status] = {};
      }
      statusMap[item.status][item.date] = item.count;
    });

    // Create series for each status, filling in missing dates with 0
    // BarChart uses "bar" type and {x, y} data format
    const series = Object.entries(statusMap).map(([status, dateMap]) => ({
      title: status,
      type: 'bar' as const,
      color: STATUS_COLORS[status] || '#879596',
      data: last7Days.map((date) => ({
        x: formatDateForDisplay(date),
        y: dateMap[date] || 0,
      })),
    }));

    // Sort series by total count (descending) to show most common statuses first
    series.sort((a, b) => {
      const sumA = a.data.reduce((acc, d) => acc + d.y, 0);
      const sumB = b.data.reduce((acc, d) => acc + d.y, 0);
      return sumB - sumA;
    });

    const hasData = series.some((s) => s.data.some((d) => d.y > 0));

    // Calculate max Y value for the stacked bars
    const maxY = categories.reduce((max, cat) => {
      const sum = series.reduce((total, s) => {
        const point = s.data.find((d) => d.x === cat);
        return total + (point?.y || 0);
      }, 0);
      return Math.max(max, sum);
    }, 0);

    return { series, categories, hasData, maxY };
  }, [data]);

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('job_trend')}</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  return (
    <Container header={<Header variant="h2">{t('job_trend')}</Header>}>
      {hasData ? (
        <BarChart
          series={series}
          xDomain={categories}
          yDomain={[0, Math.max(maxY, 10)]}
          xScaleType="categorical"
          xTitle={t('date')}
          yTitle={t('job_count')}
          stackedBars
          height={300}
          hideFilter
          ariaLabel="Job trend chart"
          empty={
            <Box textAlign="center" color="inherit">
              <b>{t('no_data')}</b>
              <Box textAlign="center" color="inherit">
                {t('no_jobs_in_period')}
              </Box>
            </Box>
          }
          noMatch={
            <SpaceBetween size="xs" alignItems="center">
              <Box fontWeight="bold" textAlign="center" color="inherit">
                {t('no_matching_data')}
              </Box>
              <Button>{t('clear_filter')}</Button>
            </SpaceBetween>
          }
        />
      ) : (
        <Box textAlign="center" color="text-body-secondary" padding="xl">
          {t('no_jobs_in_period')}
        </Box>
      )}
    </Container>
  );
}
