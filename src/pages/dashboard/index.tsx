// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useRef } from 'react';
import {
  Flashbar,
  Header,
  Grid,
  SpaceBetween,
  Button,
} from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';

import { Breadcrumbs, dashboardBreadcrumbs } from '../commons/breadcrumbs';
import { CustomAppLayout, Navigation } from '../commons/common-components';
import { TopNav } from '../commons/top-nav';
import { useSimpleNotifications } from '../commons/use-notifications';
import { useDashboardStats } from './hooks';
import { JobStatsCard } from './components/job-stats-card';
import { EndpointStatsCard } from './components/endpoint-stats-card';
import { ClusterStatsCard } from './components/cluster-stats-card';
import { JobTrendChart } from './components/job-trend-chart';

import '../../styles/base.scss';

function DashboardContent() {
  const { t } = useTranslation();
  const { stats, loading, error, refresh } = useDashboardStats();

  return (
    <SpaceBetween size="m">
      <Header
        variant="h1"
        actions={
          <Button
            iconName="refresh"
            onClick={refresh}
            loading={loading}
          >
            {t('refresh')}
          </Button>
        }
      >
        {t('dashboard')}
      </Header>
      {/* Row 1: Training Jobs + Job Trend */}
      <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
        <JobStatsCard data={stats?.job_stats} loading={loading} />
        <JobTrendChart data={stats?.job_stats?.daily_counts} loading={loading} />
      </Grid>
      {/* Row 2: Endpoints + Clusters */}
      <Grid gridDefinition={[{ colspan: 6 }, { colspan: 6 }]}>
        <EndpointStatsCard data={stats?.endpoint_stats} loading={loading} />
        <ClusterStatsCard data={stats?.cluster_stats} loading={loading} />
      </Grid>
    </SpaceBetween>
  );
}

function Dashboard() {
  const { notificationitems } = useSimpleNotifications();
  const appLayout = useRef<any>();

  return (
    <div>
      <TopNav />
      <CustomAppLayout
        ref={appLayout}
        navigation={<Navigation activeHref="/" />}
        notifications={<Flashbar items={notificationitems} stackItems />}
        breadcrumbs={<Breadcrumbs items={dashboardBreadcrumbs} />}
        content={<DashboardContent />}
        contentType="default"
      />
    </div>
  );
}

export default Dashboard;
