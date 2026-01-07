// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useRef, useState } from 'react';
import intersection from 'lodash/intersection';
import { Flashbar, Pagination, Table, TextFilter } from '@cloudscape-design/components';
import { useTranslation } from 'react-i18next';

import { COLUMN_DEFINITIONS, DEFAULT_PREFERENCES, Preferences } from './table-config';
import { Breadcrumbs, jobsBreadcrumbs } from '../commons/breadcrumbs'
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
import { remotePost } from '../../common/api-gateway';
import {DeployModelModal} from '../endpoints/create-ed';
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
  const [preferences, setPreferences] = useLocalStorage('ModelHub-JobTable-Preferences', DEFAULT_PREFERENCES);
  const [descendingSorting, setDescendingSorting] = useState(false);
  const [currentPageIndex, setCurrentPageIndex] = useState(1);
  const [filteringText, setFilteringText] = useState('');
  const [delayedFilteringText, setDelayedFilteringText] = useState('');
  const [sortingColumn, setSortingColumn] = useState(columnDefinitions[0]);
  const [refresh,setRefresh] = useState(false);
  const [visible, setVisible] = useState(false);
  const [selectedItems, setSelectedItems] = useState([]);
  const { setNotificationItems } = useSimpleNotifications();

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

  // const { items, actions, filteredItemsCount, collectionProps, filterProps, paginationProps } = useCollection(
  //   distributions,
  //   {
  //     filtering: {
  //       empty: <TableEmptyState resourceName={resourceName} />,
  //       noMatch: <TableNoMatchState onClearFilter={clearFilter} />,
  //       filteringFunction: (item, filteringText) => {
  //         if (!matchesCategory(item, cat)) {
  //           return false;
  //         }
  //         if (!matchesIndustry(item, industry)) {
  //           return false;
  //         }
  //         const filteringTextLowerCase = filteringText.toLowerCase();
  
  //         return SEARCHABLE_COLUMNS.map(key => item[key]).some(
  //           value => typeof value === 'string' && value.toLowerCase().indexOf(filteringTextLowerCase) > -1
  //         );
  //       }
  //     },
  //     pagination: { pageSize: preferences.pageSize },
  //     sorting: {defaultState: {sortingDescending:true, sortingColumn: columnDefinitions[6], isDescending:true }},
  //     selection: {},
  //   }
  // );

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

  const onDeploy =()=>{
    setVisible(true);
  }

  const onDelete = () => {
    const msgid = `msg-${Math.random().toString(8)}`;
    if (selectedItems[0].job_status === 'RUNNING'){
      setNotificationItems((item) => [
        ...item,
        {
          type: "warning",
          content: t('job_running_cannot_delete'),
          dismissible: true,
          dismissLabel: "Dismiss message",
          onDismiss: () =>
            setNotificationItems((items) =>
              items.filter((item) => item.id !== msgid)
            ),
          id: msgid,
        },
      ]);
    }else{
      remotePost({job_id:selectedItems[0].job_id},'delete_job').then(res=>{
        console.log(res);
        if (res.response.code === 'SUCCESS'){
          setNotificationItems((item) => [
            ...item,
            {
              type: "success",
              content: `${t('job_delete_success')} ${selectedItems[0].job_id}`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items) =>
                  items.filter((item) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
          setRefresh((prev)=>!prev);

        }else{
          setNotificationItems((item) => [
            ...item,
            {
              type: "error",
              content: `${selectedItems[0].job_id}. ${res.response.message}`,
              dismissible: true,
              dismissLabel: "Dismiss message",
              onDismiss: () =>
                setNotificationItems((items) =>
                  items.filter((item) => item.id !== msgid)
                ),
              id: msgid,
            },
          ]);
        }

      }).catch(err=>{
        setNotificationItems((item) => [
          ...item,
          {
            type: "error",
            content: `${t('job_delete_failed')} ${selectedItems[0].job_id}`,
            dismissible: true,
            dismissLabel: "Dismiss message",
            onDismiss: () =>
              setNotificationItems((items) =>
                items.filter((item) => item.id !== msgid)
              ),
            id: msgid,
          },
        ]);
      })
    }
  };

  const onRefresh = () => {
    setRefresh((prev)=>!prev);
  };


  return (
    <div>
    {visible&&<DeployModelModal setDisplayNotify={setDisplayNotify} setNotificationData={setNotificationData}
    selectedItems={selectedItems} setVisible={setVisible} visible={visible}/>}

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
        />
      }
      loadingText={t('loading_jobs')}
      empty={<TableNoMatchState onClearFilter={onClearFilter} />}
      filter={
        <TextFilter
          filteringText={filteringText}
          onChange={({ detail }) => setFilteringText(detail.filteringText)}
          onDelayedChange={() => setDelayedFilteringText(filteringText)}
          filteringAriaLabel={t('filter_jobs')}
          filteringPlaceholder={t('find_jobs')}
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

function JobTable() {
  const [columnDefinitions, saveWidths] = useColumnWidths('React-JobTable-Widths', COLUMN_DEFINITIONS);
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
        navigation={<Navigation activeHref="/jobs" />}
        // notifications={<Notifications successNotification={displayNotify} data={notificationData} />}
        notifications={<Flashbar items={notificationitems} stackItems/>}

        breadcrumbs={<Breadcrumbs items={jobsBreadcrumbs} />}
        content={

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
    
        }
        contentType="table"
        toolsOpen={toolsOpen}
        onToolsChange={({ detail }) => setToolsOpen(detail.open)}
      />
     
    </div>
  );
}


export default JobTable;

