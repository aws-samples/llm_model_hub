import React from 'react';
import {
  Container,
  Header,
  Box,
  SpaceBetween,
  Spinner,
  ColumnLayout,
  Table,
  Link,
  StatusIndicator,
} from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';
import { ClusterStats } from '../hooks';

interface ClusterStatsCardProps {
  data: ClusterStats | undefined;
  loading: boolean;
}

export function ClusterStatsCard({ data, loading }: ClusterStatsCardProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('cluster_stats')}</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  // Convert instance type distribution to table items
  const instanceTypeItems = data?.instance_type_distribution
    ? Object.entries(data.instance_type_distribution)
        .sort((a, b) => b[1] - a[1]) // Sort by count descending
        .slice(0, 5) // Show top 5
        .map(([type, count]) => ({ type, count }))
    : [];

  return (
    <Container header={<Header variant="h2">{t('cluster_stats')}</Header>}>
      <SpaceBetween size="m">
        <ColumnLayout columns={2} variant="text-grid">
          <Box textAlign="center">
            <Box variant="awsui-key-label">{t('total_clusters')}</Box>
            <Link href="/clusters" fontSize="display-l" variant="primary">
              {data?.total_count || 0}
            </Link>
          </Box>
          <Box textAlign="center">
            <Box variant="awsui-key-label">{t('active_clusters')}</Box>
            <Box fontSize="display-l" fontWeight="bold" color="text-status-success">
              {data?.active_count || 0}
            </Box>
          </Box>
        </ColumnLayout>

        <Box textAlign="center">
          <Box variant="awsui-key-label">{t('running_instances')}</Box>
          <Box fontSize="heading-xl" fontWeight="bold">
            {data?.total_instance_count || 0}
          </Box>
        </Box>

        {instanceTypeItems.length > 0 ? (
          <SpaceBetween size="xs">
            <Box variant="awsui-key-label">{t('instance_distribution')}</Box>
            <Table
              columnDefinitions={[
                {
                  id: 'type',
                  header: t('instance_type'),
                  cell: (item) => item.type,
                  width: 180,
                },
                {
                  id: 'count',
                  header: t('count'),
                  cell: (item) => (
                    <StatusIndicator type="success">
                      {item.count}
                    </StatusIndicator>
                  ),
                  width: 80,
                },
              ]}
              items={instanceTypeItems}
              variant="embedded"
              wrapLines={false}
            />
          </SpaceBetween>
        ) : (
          <Box textAlign="center" color="text-body-secondary" padding="s">
            {t('no_data')}
          </Box>
        )}
      </SpaceBetween>
    </Container>
  );
}
