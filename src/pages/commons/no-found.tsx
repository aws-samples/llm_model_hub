// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useRef, useState } from "react";
import { CustomAppLayout, Navigation } from "./common-components";
import { Header, ContentLayout, Link ,BreadcrumbGroup} from "@cloudscape-design/components";


const breadcrumbsItems = [
    {
      text: 'Not ready',
      href: '/home',
    },
    {
      text: 'Not ready',
      href: '#',
    },
  ];


const Breadcrumbs = () => (
    <BreadcrumbGroup items={breadcrumbsItems} expandAriaLabel="Show path" ariaLabel="Breadcrumbs" />
  );


const NotFound = () => {
  const [toolsOpen, setToolsOpen] = useState(false);
  const appLayout = useRef(null);

  return (
    <CustomAppLayout
      ref={appLayout}
      navigation={<Navigation activeHref="/home" />}
      breadcrumbs={<Breadcrumbs />}
      content={
        <ContentLayout
          header={
            <Header variant="h1" info={<Link variant="info">Info</Link>}>
              Not ready
            </Header>
          }
        >
            <br/><br/>
          <h1>Page not ready yet</h1>
        </ContentLayout>
      }
      onToolsChange={({ detail }) => setToolsOpen(detail.open)}
      stickyNotifications
    />
  );
};

export default NotFound;