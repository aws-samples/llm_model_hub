// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import  { SideNavigationProps,SideNavigation,Badge} from '@cloudscape-design/components';
import i18n from '../../common/i18n';

const navHeader = { text: 'Service', href: '#/' };
export const navItems: SideNavigationProps['items'] = [
  {
    type: 'section',
    text: 'Train Management',
    items: [
      { type: 'link', text: 'Training Jobs', href: '/jobs' },
    ],
  },
  {
    type: 'section',
    text: 'Endpoint Management',
    items: [
      { type: 'link', text: 'Endpoints', href: '/endpoints' },
    ],
  },
  {
    type: 'section',
    text: 'Playground',
    items: [
      { type: 'link', text: 'Chat', href: '/chat' },
    ],
  }, 
  {
    type: 'section',
    text: i18n.t('readme'),
    items: [
      { type: 'link', external: true, 
      info: <Badge color="green">必读</Badge>,
      text: '使用说明', href: 'https://amzn-chn.feishu.cn/docx/QniUdr7FroxShfxeoPacLJKtnXf' },
    ],
  }, 
];


interface NavigationProps {
  activeHref?: string;
  header?: SideNavigationProps['header'];
  items?: SideNavigationProps['items'];
}

export function Navigation({
  activeHref,
  header = navHeader,
  items = navItems,
}: NavigationProps) {
  return <SideNavigation items={items} header={header} activeHref={activeHref} />;
}
