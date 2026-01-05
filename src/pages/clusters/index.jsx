// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useRef, useState } from 'react';
import intersection from 'lodash/intersection';
import { Flashbar, Pagination, Table, TextFilter } from '@cloudscape-design/components';

import { COLUMN_DEFINITIONS, DEFAULT_PREFERENCES, Preferences } from './table-config';
import { Breadcrumbs, clustersBreadcrumbs } from '../commons/breadcrumbs';
import { CustomAppLayout, Navigation, TableNoMatchState } from '../commons/common-components';
import { FullPageHeader } from './full-page-header';
import { useLocalStorage } from '../commons/use-local-storage';
import {
  getHeaderCounterServerSideText,
  distributionTableAriaLabels,
  getTextFilterCounterServerSideText,
  renderAriaLive,
} from '../../i18n-strings';
import { useColumnWidths } from '../commons/use-column-widths';
import { useClusters } from './hooks';
import { TopNav } from '../commons/top-nav';
import { DeleteClusterModal } from './delete-cluster';
import { useSimpleNotifications } from '../commons/use-notifications';

import '../../styles/base.scss';

function ServerSideTable({
  columnDefinitions,
  saveWidths,
  loadHelpPanelContent,
}) {
  const [preferences, setPreferences] = useLocalStorage('ModelHub-cluster-table-Preferences', DEFAULT_PREFERENCES);
  const [descendingSorting, setDescendingSorting] = useState(false);
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const [filteringText, setFilteringText] = useState('');
  const [delayedFilteringText, setDelayedFilteringText] = useState('');
  const [sortingColumn, setSortingColumn] = useState(columnDefinitions[0]);
  const [refresh, setRefresh] = useState(false);
  const [deleteVisible, setDeleteVisible] = useState(false);
  const [selectedItems, setSelectedItems] = useState([]);
  const { pageSize } = preferences;

  const params = {
    pagination: {
      currentPageIndex,
      pageSize,
    },
    sorting: {
      sortingColumn,
      sortingDescending: descendingSorting,
    },
    filtering: {
      filteringText: delayedFilteringText,
    },
    refresh: refresh
  };

  const { items, loading, totalCount, pagesCount, currentPageIndex: serverPageIndex } = useClusters(params);

  useEffect(() => {
    setSelectedItems(oldSelected => intersection(items, oldSelected));
  }, [items]);

  const onSortingChange = event => {
    setDescendingSorting(event.detail.isDescending);
    setSortingColumn(event.detail.sortingColumn);
  };

  const onClearFilter = () => {
    setFilteringText('');
    setDelayedFilteringText('');
  };

  const onDelete = () => {
    setDeleteVisible(true);
  };

  const onRefresh = () => {
    setRefresh((prev) => !prev);
  };

  return (
    <div>
      {deleteVisible && (
        <DeleteClusterModal
          selectedItems={selectedItems}
          setVisible={setDeleteVisible}
          visible={deleteVisible}
          onRefresh={onRefresh}
        />
      )}

      <Table
        enableKeyboardNavigation={true}
        loading={loading}
        selectedItems={selectedItems}
        items={items}
        onSortingChange={onSortingChange}
        onSelectionChange={event => setSelectedItems(event.detail.selectedItems)}
        sortingColumn={sortingColumn}
        sortingDescending={descendingSorting}
        columnDefinitions={columnDefinitions}
        columnDisplay={preferences.contentDisplay}
        ariaLabels={distributionTableAriaLabels}
        renderAriaLive={renderAriaLive}
        selectionType="single"
        variant="full-page"
        stickyHeader={true}
        resizableColumns={true}
        onColumnWidthsChange={saveWidths}
        wrapLines={preferences.wrapLines}
        stripedRows={preferences.stripedRows}
        contentDensity={preferences.contentDensity}
        stickyColumns={preferences.stickyColumns}
        header={
          <FullPageHeader
            selectedItemsCount={selectedItems.length}
            selectedItems={selectedItems}
            onDelete={onDelete}
            counter={!loading && getHeaderCounterServerSideText(totalCount, selectedItems.length)}
            onInfoLinkClick={loadHelpPanelContent}
            onRefresh={onRefresh}
          />
        }
        loadingText="Loading clusters"
        empty={<TableNoMatchState onClearFilter={onClearFilter} />}
        filter={
          <TextFilter
            filteringText={filteringText}
            onChange={({ detail }) => setFilteringText(detail.filteringText)}
            onDelayedChange={() => setDelayedFilteringText(filteringText)}
            filteringAriaLabel="Filter clusters"
            filteringPlaceholder="Find clusters"
            filteringClearAriaLabel="Clear"
            countText={getTextFilterCounterServerSideText(items, pagesCount, pageSize)}
          />
        }
        pagination={
          <Pagination
            pagesCount={pagesCount}
            currentPageIndex={serverPageIndex}
            disabled={loading}
            onChange={event => setCurrentPageIndex(event.detail.currentPageIndex)}
          />
        }
        preferences={<Preferences preferences={preferences} setPreferences={setPreferences} />}
      />
    </div>
  );
}

function ClustersTable() {
  const [columnDefinitions, saveWidths] = useColumnWidths('React-ClusterTable-Widths', COLUMN_DEFINITIONS);
  const [toolsOpen, setToolsOpen] = useState(false);
  const { notificationitems } = useSimpleNotifications();
  const appLayout = useRef();

  return (
    <div>
      <TopNav />
      <CustomAppLayout
        ref={appLayout}
        navigation={<Navigation activeHref="/clusters" />}
        notifications={<Flashbar items={notificationitems} stackItems />}
        breadcrumbs={<Breadcrumbs items={clustersBreadcrumbs} />}
        content={
          <div>
            <ServerSideTable
              columnDefinitions={columnDefinitions}
              saveWidths={saveWidths}
              loadHelpPanelContent={() => {
                setToolsOpen(true);
                appLayout.current?.focusToolsClose();
              }}
            />
          </div>
        }
        contentType="table"
        toolsOpen={toolsOpen}
        onToolsChange={({ detail }) => setToolsOpen(detail.open)}
      />
    </div>
  );
}

export default ClustersTable;
