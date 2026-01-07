// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import { SideNavigationProps, SideNavigation, Badge } from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';

interface NavigationProps {
  activeHref?: string;
  header?: SideNavigationProps['header'];
  items?: SideNavigationProps['items'];
}

export function Navigation({
  activeHref,
  header,
  items,
}: NavigationProps) {
  const { t } = useTranslation();

  const navHeader = header || { text: t('service'), href: '#/' };

  const navItems: SideNavigationProps['items'] = items || [
    {
      type: 'section',
      text: t('train_management'),
      items: [
        { type: 'link', text: t('training_jobs'), href: '/jobs' },
      ],
    },
    {
      type: 'section',
      text: t('endpoint_management'),
      items: [
        { type: 'link', text: t('endpoints'), href: '/endpoints' },
      ],
    },
    {
      type: 'section',
      text: t('cluster_management'),
      items: [
        { type: 'link', text: t('hyperpod_clusters'), href: '/clusters' },
      ],
    },
    {
      type: 'section',
      text: t('playground'),
      items: [
        { type: 'link', text: t('chat'), href: '/chat' },
      ],
    },
    {
      type: 'section',
      text: t('user_guide'),
      items: [
        {
          type: 'link',
          external: true,
          info: <Badge color="green">{t('must_read')}</Badge>,
          text: t('user_guide'),
          href: 'https://amzn-chn.feishu.cn/docx/QniUdr7FroxShfxeoPacLJKtnXf'
        },
      ],
    },
  ];

  return <SideNavigation items={navItems} header={navHeader} activeHref={activeHref} />;
}
