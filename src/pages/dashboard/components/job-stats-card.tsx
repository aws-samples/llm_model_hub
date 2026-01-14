import React from 'react';
import {
  Container,
  Header,
  Box,
  SpaceBetween,
  Spinner,
  PieChart,
  Link,
} from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';
import { JobStats } from '../hooks';

interface JobStatsCardProps {
  data: JobStats | undefined;
  loading: boolean;
}

// Status color mapping for visual consistency
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

export function JobStatsCard({ data, loading }: JobStatsCardProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('job_stats')}</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  const statusData = data?.by_status
    ? Object.entries(data.by_status)
        .filter(([_, value]) => value > 0)
        .map(([key, value]) => ({
          title: key,
          value: value,
          color: STATUS_COLORS[key] || '#879596',
        }))
    : [];

  const hasData = statusData.length > 0;

  return (
    <Container header={<Header variant="h2">{t('job_stats')}</Header>}>
      <SpaceBetween size="m">
        <Box textAlign="center">
          <Box variant="awsui-key-label">{t('total_jobs')}</Box>
          <Link href="/jobs" fontSize="display-l" variant="primary">
            {data?.total_count || 0}
          </Link>
        </Box>
        {hasData ? (
          <PieChart
            data={statusData}
            detailPopoverContent={(datum, sum) => [
              { key: t('status'), value: datum.title },
              { key: t('count'), value: datum.value.toString() },
              {
                key: t('percentage'),
                value: `${((datum.value / sum) * 100).toFixed(1)}%`,
              },
            ]}
            segmentDescription={(datum, sum) =>
              `${datum.title}: ${datum.value} (${((datum.value / sum) * 100).toFixed(1)}%)`
            }
            size="medium"
            hideFilter
            hideLegend={false}
            legendTitle={t('status_distribution')}
            empty={
              <Box textAlign="center" color="inherit">
                <b>{t('no_data')}</b>
              </Box>
            }
          />
        ) : (
          <Box textAlign="center" color="text-body-secondary" padding="l">
            {t('no_data')}
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
}
