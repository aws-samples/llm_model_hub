// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import BreadcrumbGroup, { BreadcrumbGroupProps } from '@cloudscape-design/components/breadcrumb-group';

export const jobsBreadcrumbs = [
  {
    text: 'Jobs',
    href: '/jobs',
  },
];

export const createjobBreadcrumbs = [
  ...jobsBreadcrumbs,
  {
    text: 'Create Job',
    href: '/jobs/createjob',
  },
];

export const endpointsBreadcrumbs = [
  {
    text: 'Endpoints',
    href: '/endpoints',
  },
];

export const chatBreadcrumbs = [
  {
    text: 'Playground',
    href: '/playground',
  },
];


export function Breadcrumbs({ items }: { items: BreadcrumbGroupProps['items'] }) {
  return (
    <BreadcrumbGroup
      items={[{ text: 'Model Hub', href: '/jobs' }, ...items]}
      expandAriaLabel="Show path"
      ariaLabel="Breadcrumbs"
    />
  );
}
