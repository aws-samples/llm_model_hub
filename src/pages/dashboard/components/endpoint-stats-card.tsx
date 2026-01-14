import React from 'react';
import {
  Container,
  Header,
  Box,
  SpaceBetween,
  Spinner,
  PieChart,
  ColumnLayout,
  Link,
} from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';
import { EndpointStats } from '../hooks';

interface EndpointStatsCardProps {
  data: EndpointStats | undefined;
  loading: boolean;
}

// Deployment target colors
const TARGET_COLORS: Record<string, string> = {
  sagemaker: '#0972d3',  // Blue
  hyperpod: '#037f0c',   // Green
};

export function EndpointStatsCard({ data, loading }: EndpointStatsCardProps) {
  const { t } = useTranslation();

  if (loading) {
    return (
      <Container header={<Header variant="h2">{t('endpoint_stats')}</Header>}>
        <Box textAlign="center" padding="l">
          <Spinner size="large" />
        </Box>
      </Container>
    );
  }

  const sagemakerCount = data?.by_deployment_target?.sagemaker || 0;
  const hyperpodCount = data?.by_deployment_target?.hyperpod || 0;

  const deploymentTargetData = data?.by_deployment_target
    ? Object.entries(data.by_deployment_target)
        .filter(([_, value]) => value > 0)
        .map(([key, value]) => ({
          title: key === 'sagemaker' ? 'SageMaker' : 'HyperPod',
          value: value,
          color: TARGET_COLORS[key] || '#879596',
        }))
    : [];

  const hasData = deploymentTargetData.length > 0;

  return (
    <Container header={<Header variant="h2">{t('endpoint_stats')}</Header>}>
      <SpaceBetween size="m">
        <ColumnLayout columns={2} variant="text-grid">
          <Box textAlign="center">
            <Box variant="awsui-key-label">{t('sagemaker_endpoints')}</Box>
            <Link href="/endpoints" fontSize="display-l" variant="primary">
              {sagemakerCount}
            </Link>
          </Box>
          <Box textAlign="center">
            <Box variant="awsui-key-label">{t('hyperpod_endpoints')}</Box>
            <Link href="/endpoints" fontSize="display-l" variant="primary">
              {hyperpodCount}
            </Link>
          </Box>
        </ColumnLayout>
        {hasData ? (
          <PieChart
            data={deploymentTargetData}
            detailPopoverContent={(datum, sum) => [
              { key: t('type'), value: datum.title },
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
            legendTitle={t('deployment_target')}
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
