// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React from 'react';
import {
  CollectionPreferences,
  StatusIndicator,
  Link,

} from '@cloudscape-design/components';
import { createTableSortLabelFn } from '../../i18n-strings';

const rawColumns = [
  {
    id: 'id',
    sortingField: 'id',
    header: 'ID',
    cell: item => (
      <div>
        <Link href={`/jobs/${item.job_id}`}>{item.job_id}</Link>
      </div>
    ),
    minWidth: 180,
  },
  {
    id: 'status',
    sortingField: 'status',
    header: 'Status',
    cell: item => (
      <StatusIndicator type={item.job_status === 'SUCCESS' ? 'success' : 
        item.job_status === 'ERROR' ? "error" : 
        item.job_status === 'STOPPED' ? "stopped" : "in-progress"
      }>{item.job_status}</StatusIndicator>
    ),
    minWidth: 120,
  },
  {
    id: 'type',
    sortingField: 'type',
    cell: item => item.job_type,
    header: 'Type',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'finetune_method',
    sortingField: 'finetune_method',
    cell: item => item.job_payload?.finetuning_method,
    header: 'Finetune',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'model_name',
    sortingField: 'model_name',
    cell: item => item.job_payload?.model_name,
    header: 'Model Name',
    minWidth: 40,
    isRowHeader: true,
  },
  {
    id: 'name',
    sortingField: 'name',
    cell: item => item.job_name,
    header: 'Name',
    minWidth: 50,
    isRowHeader: true,
  },
  {
    id: 'sm_name',
    sortingField: 'sm_name',
    cell: item => item.job_run_name,
    header: 'SM Job Name',
    minWidth: 160,
    isRowHeader: true,
  },
  {
    id: 'create_time',
    sortingField: 'create_time',
    // cell: item => formatDateTime(item.job_create_time),
    cell: item => item.job_create_time,
    header: 'Create Time',
    minWidth: 120,
    isRowHeader: true,
  },
  {
    id: 'start_time',
    sortingField: 'start_time',
    // cell: item => formatDateTime(item.job_start_time),
    cell: item => item.job_start_time,
    header: 'Start Time',
    minWidth: 120,
    isRowHeader: true,
  },
  {
    id: 'end_time',
    sortingField: 'end_time',
    // cell: item => formatDateTime(item.job_end_time),
    cell: item => item.job_end_time,
    header: 'End Time',
    minWidth: 120,
    isRowHeader: true,
  },
  {
    id: 'output_s3_path',
    sortingField: 'output_s3_path',
    cell: item => item.output_s3_path,
    header: 'Output S3 Path',
    minWidth: 160,
    isRowHeader: true,
  },
  // {
  //   id: 'actions',
  //   header: 'Actions',
  //   minWidth: 100,
  //   cell: item => (
  //     <ButtonDropdown
  //       variant="inline-icon"
  //       ariaLabel={`${item.id} actions`}
  //       expandToViewport={true}
  //       items={[
  //         { id: 'view', text: 'View details' },
  //         { id: 'edit', text: 'Edit' },
  //         { id: 'delete', text: 'Delete' },
  //       ]}
  //     />
  //   ),
  // },
];


export const JOB_STATE = {
  PENDING : "PENDING",
  SUBMITTED : "SUBMITTED",
  CREATING : "CREATING",
  RUNNING : "RUNNING",
  SUCCESS : "SUCCESS",
  ERROR : "ERROR",
  TERMINATED : "TERMINATED",
  TERMINATING : "TERMINATING",
  STOPPED : "STOPPED"
}

export const COLUMN_DEFINITIONS = rawColumns.map(column => ({ ...column, ariaLabel: createTableSortLabelFn(column) }));

export const serverSideErrorsStore = new Map();


const CONTENT_DISPLAY_OPTIONS = [
  { id: 'id', label: 'ID', alwaysVisible: true },
  { id: 'status', label: 'Status' },
  { id: 'model_name', label: 'Model Name' },
  { id: 'type', label: 'Type' },
  { id :'finetune_method', lable: 'Finetune'},
  { id: 'name', label: 'Name' },
  { id: 'sm_name', label: 'SM Job Name' },
  { id: 'create_time', label: 'Create Time' },
  { id: 'start_time', label: 'Start Time' },
  { id: 'end_time', label: 'End Time' },
  { id: 'output_s3_path', label: 'Output S3 Path' }
];

export const PAGE_SIZE_OPTIONS = [
  { value: 50, label: '50 Records' },
  { value: 30, label: '30 Records' },
  { value: 10, label: '10 Records' },
];

export const DEFAULT_PREFERENCES = {
  pageSize: 30,
  contentDisplay: [
    { id: 'id', visible: true },
    { id: 'status', visible: true },
    { id: 'name', visible: true },
    { id: 'sm_name', visible: true },
    { id: 'model_name', visible: true },
    { id: 'type', visible: true },
    { id: 'finetune_method', visible: true },
    { id: 'create_time', visible: true },
    { id: 'start_time', visible: false },
    { id: 'end_time', visible: false },
    { id: 'output_s3_path', visible: true }
  ],
  wrapLines: false,
  stripedRows: false,
  contentDensity: 'comfortable',
  stickyColumns: { first: 0, last: 1 },
};

export const Preferences = ({
  preferences,
  setPreferences,
  disabled,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
  contentDisplayOptions = CONTENT_DISPLAY_OPTIONS,
}) => (
  <CollectionPreferences
    disabled={disabled}
    preferences={preferences}
    onConfirm={({ detail }) => setPreferences(detail)}
    pageSizePreference={{ options: pageSizeOptions }}
    wrapLinesPreference={{}}
    stripedRowsPreference={{}}
    contentDensityPreference={{}}
    contentDisplayPreference={{ options: contentDisplayOptions }}
    stickyColumnsPreference={{
      firstColumns: {
        title: 'Stick first column(s)',
        description: 'Keep the first column(s) visible while horizontally scrolling the table content.',
        options: [
          { label: 'None', value: 0 },
          { label: 'First column', value: 1 },
          { label: 'First two columns', value: 2 },
        ],
      },
      lastColumns: {
        title: 'Stick last column',
        description: 'Keep the last column visible while horizontally scrolling the table content.',
        options: [
          { label: 'None', value: 0 },
          { label: 'Last column', value: 1 },
        ],
      },
    }}
  />
);
