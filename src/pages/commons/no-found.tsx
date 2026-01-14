// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useRef, useState } from "react";
import { CustomAppLayout, Navigation } from "./common-components";
import { Header, ContentLayout, Link, BreadcrumbGroup, Button } from "@cloudscape-design/components";
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';


const NotFound = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [toolsOpen, setToolsOpen] = useState(false);
  const appLayout = useRef(null);

  const breadcrumbsItems = [
    {
      text: t('home'),
      href: '/',
    },
    {
      text: t('page_not_found'),
      href: '#',
    },
  ];

  const Breadcrumbs = () => (
    <BreadcrumbGroup items={breadcrumbsItems} expandAriaLabel="Show path" ariaLabel="Breadcrumbs" />
  );

  return (
    <CustomAppLayout
      ref={appLayout}
      navigation={<Navigation activeHref="/home" />}
      breadcrumbs={<Breadcrumbs />}
      content={
        <ContentLayout
          header={
            <Header variant="h1" info={<Link variant="info">{t('info')}</Link>}>
              {t('page_not_found')}
            </Header>
          }
        >
          <br/><br/>
          <p>{t('page_not_found_desc')}</p>
          <br/>
          <Button variant="primary" onClick={() => navigate('/')}>
            {t('go_home')}
          </Button>
        </ContentLayout>
      }
      onToolsChange={({ detail }) => setToolsOpen(detail.open)}
      stickyNotifications
    />
  );
};

export default NotFound;