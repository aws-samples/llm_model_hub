// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useRef, useState } from 'react';
import intersection from 'lodash/intersection';
import { Flashbar, Pagination, Table, TextFilter } from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';

import { COLUMN_DEFINITIONS, DEFAULT_PREFERENCES, Preferences } from './table-config';
import { Breadcrumbs, endpointsBreadcrumbs } from '../commons/breadcrumbs'
import { CustomAppLayout, Navigation, Notifications, TableNoMatchState } from '../commons/common-components';
import { FullPageHeader } from './full-page-header';
import { useLocalStorage } from '../commons/use-local-storage';
import {
  getHeaderCounterServerSideText,
  distributionTableAriaLabels,
  getTextFilterCounterServerSideText,
  renderAriaLive,
} from '../../i18n-strings';
import { useColumnWidths } from '../commons/use-column-widths';
import { useDistributions } from './hooks';
import { TopNav } from '../commons/top-nav';
import {DeleteModelModal} from '../endpoints/delete-ed';
import {DeployModelModal} from '../endpoints/create-ed';
import {ViewCodeModal} from '../endpoints/view-code';
import {useSimpleNotifications} from '../commons/use-notifications';

import '../../styles/base.scss';

function ServerSideTable({
  columnDefinitions,
  saveWidths,
  loadHelpPanelContent,
  setDisplayNotify,
  setNotificationData
}) {
  const { t } = useTranslation();
  const [preferences, setPreferences] = useLocalStorage('ModelHub-endpoint-table-Preferences', DEFAULT_PREFERENCES);
  const [descendingSorting, setDescendingSorting] = useState(false);
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const [filteringText, setFilteringText] = useState('');
  const [delayedFilteringText, setDelayedFilteringText] = useState('');
  const [sortingColumn, setSortingColumn] = useState(columnDefinitions[0]);
  const [refresh,setRefresh] = useState(false);
  const [visible, setVisible] = useState(false);
  const [codeVisible,setCodeVisible] = useState(false);
  const [deployVisible, setDeployVisible] = useState(false);
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
    refresh:refresh
  };
  const { items, loading, totalCount, pagesCount, currentPageIndex: serverPageIndex } = useDistributions(params);

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

  const onDelete =()=>{
    setVisible(true);
  }

  const onViewCode = ()=>{
    setCodeVisible(true);
  }

  const onRefresh = () => {
    setRefresh((prev)=>!prev);
  };

  const onDeploy =()=>{
    setDeployVisible(true);
  }

  return (
    <div>
    {visible&&<DeleteModelModal setDisplayNotify={setDisplayNotify} setNotificationData={setNotificationData} onRefresh={onRefresh}
    selectedItems={selectedItems} setVisible={setVisible} visible={visible}/>}
    {deployVisible&&<DeployModelModal setDisplayNotify={setDisplayNotify} setNotificationData={setNotificationData} onRefresh={onRefresh}
    selectedItems={selectedItems} setVisible={setDeployVisible} visible={deployVisible}/>}
    {codeVisible&&<ViewCodeModal selectedItems={selectedItems} setVisible={setCodeVisible} visible={codeVisible}/>}

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
          onDelete = {onDelete}
          onDeploy = {onDeploy}
          setNotificationData = {setNotificationData}
          setDisplayNotify = {setDisplayNotify}
          counter={!loading && getHeaderCounterServerSideText(totalCount, selectedItems.length)}
          onInfoLinkClick={loadHelpPanelContent}
          onRefresh={onRefresh}
          onViewCode={onViewCode}
        />
      }
      loadingText={t('loading_endpoints')}
      empty={<TableNoMatchState onClearFilter={onClearFilter} />}
      filter={
        <TextFilter
          filteringText={filteringText}
          onChange={({ detail }) => setFilteringText(detail.filteringText)}
          onDelayedChange={() => setDelayedFilteringText(filteringText)}
          filteringAriaLabel={t('filter_endpoints')}
          filteringPlaceholder={t('find_endpoints')}
          filteringClearAriaLabel={t('clear')}
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

function EndpointsTable() {
  const [columnDefinitions, saveWidths] = useColumnWidths('React-Endpointtable-Widths', COLUMN_DEFINITIONS);
  const [toolsOpen, setToolsOpen] = useState(false);
  const [notificationData, setNotificationData] = useState({});
  const [displayNotify, setDisplayNotify] = useState(false);
  const {notificationitems} = useSimpleNotifications();


  const appLayout = useRef();
  return (
    <div>
      <TopNav />
      <CustomAppLayout
        ref={appLayout}
        navigation={<Navigation activeHref="/endpoints" />}
        // notifications={<Notifications successNotification={displayNotify} data={notificationData} />}
        notifications={<Flashbar items={notificationitems} stackItems/>}

        breadcrumbs={<Breadcrumbs items={endpointsBreadcrumbs} />}
        content={
          <div>
          <ServerSideTable
            setNotificationData={setNotificationData}
            setDisplayNotify={setDisplayNotify}
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


export default EndpointsTable;

