// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
import React, { useEffect, useState,useCallback,useRef } from 'react';
import { remotePost } from '../../../../common/api-gateway';
import FormField from "@cloudscape-design/components/form-field";
import Container  from '@cloudscape-design/components/container';
import Header from "@cloudscape-design/components/header";
import S3ResourceSelector from "@cloudscape-design/components/s3-resource-selector";
import Alert from "@cloudscape-design/components/alert";

function SelfDismissibleAlert(props) {
    const [visible, setVisible] = useState(true);
    return (visible&& <Alert {...props}  dismissible={true} onDismiss={() => setVisible(false)} />);
  }


export const S3Path = ({outputPath,label}) => {
  return <Container
         header={<Header variant="h2"
            >{label}</Header>} >

              <FormField
                label={label}
                description={outputPath}
                stretch={false}
              >
                <S3Selector outputPath={outputPath} label={label}/>
              </FormField>
    </Container>
}
export const S3Selector = ({outputPath,objectsIsItemDisabled,setOutputPath}) => {
    const [fetchError, setFetchError] = useState(null);

    const [resource, setResource] = useState({
        uri: outputPath||""//.replace('s3://','')
      });

    const onFetchObjects = async (bucketName, pathPrefix) => {
        // console.log(`bucketName:${bucketName},pathPrefix:${pathPrefix}`)
        try{
            // const pathPrefixNew = pathPrefix.endsWith('/') ? pathPrefix : pathPrefix + '/';
            const resp = await remotePost({"output_s3_path":bucketName+pathPrefix}, 'list_s3_path');
            const objects = await resp.objects;
            // console.log('objects:',objects);
            return Promise.resolve(objects)
        }catch(err){
            console.log(err);
            setFetchError(err.message);
            return Promise.resolve([])
        }
    };

    return (
            <S3ResourceSelector
                onChange={({ detail }) =>{
                    const uri = detail.resource.uri.replace('s3://s3://','s3://')
                    // const uri_new = uri.endsWith('/') ? uri : uri + '/';
                    // setResource(detail.resource);
                    setResource({uri:uri});
                    setOutputPath&&setOutputPath(uri);
                    
                    }
                }
                alert={
                    fetchError && (
                      <SelfDismissibleAlert type="error" header="Data fetching error">
                        {fetchError}
                      </SelfDismissibleAlert>
                    )
                  }
                objectsIsItemDisabled={objectsIsItemDisabled}
                resource={resource}
                // objectsIsItemDisabled={item => item.IsFolder}
                selectableItemsTypes={[
                    "buckets",
                    "objects",
                    "version",
                  ]}
                fetchVersions={() => new Promise(() => {})}
                bucketsVisibleColumns={["Name"]}
                fetchObjects={onFetchObjects}
                fetchBuckets={() =>
                    Promise.resolve([
                      {
                        Name: resource.uri.replace('s3://s3://','s3://')
                      }
                    ])
                  }
            />

    )
}